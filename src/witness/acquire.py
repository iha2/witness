"""PR fetcher (T3): host detection, SHA resolution, worktrees, hunks."""

import json
import os
import re
import subprocess
from pathlib import Path

from witness.shared import EnvError, Hunk, PRInfo, UsageError, hunk_id

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_RENAME_RE = re.compile(r"^R\d+\t(.+?)\t(.+)$")
_RENAME_WS_RE = re.compile(r"^R\d+\s+(\S+)\s+(\S+)\s*$")
_SECRET_ENV = ("GITHUB_TOKEN", "GH_TOKEN", "WITNESS_BITBUCKET_TOKEN", "ANTHROPIC_API_KEY")
_USERINFO_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/\s@]+@")
_HEADER_RE = re.compile(
    r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*(?:(?:bearer|basic|token)\s+)?[^\s'\"]+"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")


def redact(text: str) -> str:
    """Strip credentials (URL userinfo, auth headers, known token env values)."""
    for name in _SECRET_ENV:
        val = os.environ.get(name)
        if val:
            text = text.replace(val, "***")
    text = _USERINFO_RE.sub(r"\1***@", text)
    text = _HEADER_RE.sub(lambda m: f"{m.group(1)}: ***", text)
    return _BEARER_RE.sub(lambda m: f"{m.group(1)} ***", text)


def _run(argv: list[str], cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise EnvError(f"{redact(argv[0])} not found") from exc
    if proc.returncode != 0:
        head = redact(" ".join(argv[:3]))
        raise EnvError(f"{head} failed: {redact(proc.stderr.strip())[:200]}")
    return proc.stdout


def _unquote(raw: str) -> str:
    """Decode a git C-quoted path ("\\303\\251.py") to text."""
    raw = raw.strip()
    if not (len(raw) >= 2 and raw.startswith('"') and raw.endswith('"')):
        return raw
    body = raw[1:-1]
    out = bytearray()
    i = 0
    esc = {"n": 10, "t": 9, "r": 13, "\\": 92, '"': 34, "a": 7, "b": 8, "f": 12, "v": 11}
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n in "01234567":
                j = i + 1
                while j < len(body) and j < i + 4 and body[j] in "01234567":
                    j += 1
                out.append(int(body[i + 1 : j], 8))
                i = j
                continue
            out.append(esc.get(n, ord(n)))
            i += 2
            continue
        out.extend(c.encode())
        i += 1
    return out.decode("utf-8", errors="replace")


def _side_path(line: str) -> str:
    """Path from a '--- ' or '+++ ' line; '' for /dev/null."""
    p = _unquote(line[4:].split("\t")[0])
    if p == "/dev/null":
        return ""
    return p[2:] if p[:2] in ("a/", "b/") else p


def parse_hunks(diff_text: str) -> list[Hunk]:
    """Parse a unified diff (git diff -U0) into Hunks with stable ids."""
    hunks: list[Hunk] = []
    old_path = new_path = ""
    cur: tuple[int, int, int, int] | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal cur, body
        if cur is not None:
            text = "\n".join(body)
            os_, ol, ns, nl = cur
            hunks.append(Hunk(hunk_id(new_path, os_, ns, text), old_path, new_path, os_, ol, ns, nl, text))
        cur, body = None, []

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            flush()
            old_path = new_path = ""
        elif cur is None and line.startswith("--- "):
            old_path = _side_path(line)
        elif cur is None and line.startswith("+++ "):
            new_path = _side_path(line)
        elif line.startswith("@@"):
            flush()
            m = _HUNK_RE.match(line)
            if m:
                cur = (
                    int(m.group(1)),
                    int(m.group(2) if m.group(2) is not None else 1),
                    int(m.group(3)),
                    int(m.group(4) if m.group(4) is not None else 1),
                )
        elif cur is not None:
            body.append(line)
    flush()
    return hunks


def renames(diff_text: str) -> dict[str, str]:
    """Map old path -> new path from rename headers or `R087 a b` lines."""
    out: dict[str, str] = {}
    pending: str | None = None
    for line in diff_text.splitlines():
        m = _RENAME_RE.match(line) or (None if "\t" in line else _RENAME_WS_RE.match(line))
        if m:
            out[_unquote(m.group(1))] = _unquote(m.group(2))
        elif line.startswith("rename from "):
            pending = _unquote(line[len("rename from ") :])
        elif line.startswith("rename to ") and pending is not None:
            out[pending] = _unquote(line[len("rename to ") :])
            pending = None
    return out


def host_for(remote_url: str) -> str:
    """Classify a git remote URL as github, bitbucket or other."""
    u = remote_url.lower()
    if "bitbucket" in u:
        return "bitbucket"
    if "github" in u:
        return "github"
    return "other"


def _has_commit(repo: Path, sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo, capture_output=True
        ).returncode
        == 0
    )


def _ensure(repo: Path, sha: str) -> None:
    if not _has_commit(repo, sha):
        _run(["git", "fetch", "origin", sha], repo)


def resolve_pr(ref: str, repo: Path) -> PRInfo:
    """Resolve a PR ref (or `base..head` revs) to PRInfo; base is the merge-base."""
    repo = Path(repo)
    remote = _run(["git", "remote", "get-url", "origin"], repo).strip() if _has_origin(repo) else ""
    host = host_for(remote)
    if ".." in ref and not ref.startswith("http"):
        b, h = ref.split("..", 1)
        base_rev = _run(["git", "rev-parse", b], repo).strip()
        head = _run(["git", "rev-parse", h], repo).strip()
        title = body = ""
    elif host == "bitbucket" or "bitbucket.org" in ref:
        from witness.bitbucket import BitbucketHost

        info = BitbucketHost().fetch(ref)
        base_rev, head, title, body = info.base_sha, info.head_sha, info.title, info.body
        host = "bitbucket"
    else:
        if not ref:
            raise UsageError("empty PR ref")
        raw = _run(["gh", "pr", "view", ref, "--json", "baseRefOid,headRefOid,title,body"], repo)
        data = json.loads(raw)
        base_rev, head = data["baseRefOid"], data["headRefOid"]
        title, body = data.get("title", ""), data.get("body", "")
        host = "github"
    _ensure(repo, head)
    _ensure(repo, base_rev)
    base = _run(["git", "merge-base", base_rev, head], repo).strip()
    return PRInfo(host, base, head, title, body)


def _has_origin(repo: Path) -> bool:
    return (
        subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True
        ).returncode
        == 0
    )


def checkout(repo: Path, sha: str, cache: Path) -> Path:
    """Return a detached worktree for sha under cache/wt/<sha>, reusing it if present."""
    wt = Path(cache) / "wt" / sha
    if (wt / ".git").exists():
        return wt
    wt.parent.mkdir(parents=True, exist_ok=True)
    _ensure(Path(repo), sha)
    _run(["git", "worktree", "add", "--detach", str(wt), sha], Path(repo))
    return wt
