"""Scope finder (T5): changed files plus files that mention changed names."""

import re
import subprocess
from pathlib import Path

from witness.shared import Hunk, Scope

_DEF_RE = re.compile(
    r"^(?P<indent>\s*)(?:(?:async|export|public|private|protected|static|final)\s+)*"
    r"(?:def|class|function|func|fn|fun|sub)\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_$][\w$]*)"
)
_NULL_PATHS = {"", "/dev/null"}


def _changed_path(h: Hunk) -> str:
    """Head path of a hunk, or the base path when the file was deleted."""
    return h.old_path if h.new_path in _NULL_PATHS else h.new_path


def _module_name(path: str) -> str:
    return str(Path(path).with_suffix("")).replace("/", ".")


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip())


def _enclosing_def(lines: list[str], line_no: int) -> str | None:
    """Name of the innermost def/class that encloses the 1-based line."""
    if not lines:
        return None
    idx = min(max(line_no, 1), len(lines)) - 1
    cur = _indent(lines[idx])
    for i in range(idx, -1, -1):
        text = lines[i]
        if not text.strip():
            continue
        m = _DEF_RE.match(text)
        if m and (i == idx or len(m["indent"]) < cur):
            return m["name"]
        cur = min(cur, _indent(text))
    return None


def changed_names(repo: Path, hunks: list[Hunk]) -> list[str]:
    """Enclosing function names then module names for the hunks, deduplicated."""
    funcs: list[str] = []
    modules: list[str] = []
    for h in hunks:
        path = _changed_path(h)
        mod = _module_name(path)
        if mod not in modules:
            modules.append(mod)
        start = h.old_start if h.new_path in _NULL_PATHS else h.new_start
        try:
            lines = (repo / path).read_text(errors="replace").splitlines()
        except OSError:
            continue
        name = _enclosing_def(lines, start)
        if name and name not in funcs:
            funcs.append(name)
    return funcs + [m for m in modules if m not in funcs]


def _grep_files(repo: Path, ref: str, name: str) -> list[str]:
    """Files at `ref` that mention `name` literally (git grep -F)."""
    argv = ["git", "grep", "-l", "-I", "-F", "-e", name, ref, "--"]
    proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        return []
    prefix = ref + ":"
    return [
        ln[len(prefix):] if ln.startswith(prefix) else ln
        for ln in proc.stdout.splitlines()
        if ln
    ]


def find_scope(
    repo: Path,
    base: str,
    head: str,
    hunks: list[Hunk],
    hops: int,
    max_files: int,
) -> Scope:
    """Changed files first, then files mentioning changed names (base and head), capped.

    Changed files are never dropped by the cap.
    """
    changed: list[str] = []
    for h in hunks:
        p = _changed_path(h)
        if p not in changed:
            changed.append(p)
    found: list[str] = []
    seen = set(changed)
    names = changed_names(repo, hunks)
    for _ in range(max(hops, 0)):
        new_files: list[str] = []
        for name in names:
            for ref in (head, base):
                for f in _grep_files(repo, ref, name):
                    if f not in seen:
                        seen.add(f)
                        new_files.append(f)
        if not new_files:
            break
        found.extend(sorted(new_files))
        names = [_module_name(f) for f in sorted(new_files)]
    room = max(max_files - len(changed), 0)
    return Scope(files=changed + found[:room], unanalysed=found[room:])
