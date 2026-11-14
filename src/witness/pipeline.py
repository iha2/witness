"""Pipeline (T15): fetch -> scope -> Joern -> tag -> match -> diff -> reduce -> explain -> report."""

import os
import re
from dataclasses import asdict, replace
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from witness import acquire, explain as explain_mod, rules, scope as scope_mod
from witness.shared import EnvError, FlowChange, Hunk, NotImplementedStub, PRInfo

_LANGS = {".py": "python", ".js": "javascript", ".ts": "javascript", ".java": "java",
          ".go": "go", ".rb": "ruby", ".php": "php", ".c": "c", ".cpp": "c", ".cs": "csharp"}
_CITE = re.compile(r"\bF(\d+)\b")


class JoernMissing(EnvError):
    """Joern is not installed (partial result, exit 4)."""


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if proc.returncode != 0:
        raise EnvError(f"git {args[0]} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


def _default_build(checkout: Path, files: list[str]) -> tuple[object, str]:
    if shutil.which("joern") is None or shutil.which("joern-parse") is None:
        raise JoernMissing("joern not found")
    from witness.engines import joern

    version = joern.joern_version()
    return joern.JoernEngine().build(checkout, files, os.environ.get("WITNESS_JOERN_HEAP", "8g")), version


def _default_flow_diff(base, head, m):  # noqa: ANN001
    from witness.diff import flow_diff

    return flow_diff(base, head, m)


def _default_reduce(head, seeds, changes, budget):  # noqa: ANN001
    from witness.reduce import reduce_slice

    return reduce_slice(head, seeds, changes, budget)


def _default_llm() -> Callable[[str], str] | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic()

    def call(prompt: str) -> str:
        r = client.messages.create(
            model=os.environ.get("WITNESS_MODEL", "claude-sonnet-5-5"),
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(getattr(b, "text", "") for b in r.content)

    return call


def _lang(files: list[str]) -> str:
    for f in files:
        lang = _LANGS.get(Path(f).suffix.lower())
        if lang:
            return lang
    return "python"


def _hunk_end(h: Hunk) -> int:
    return h.new_start + max(h.new_len - 1, 0)


def _seed_map(hunks, bg, hg, m, rename_map) -> dict[str, list[int]]:  # noqa: ANN001
    """Head-graph seed ids per hunk: head ids from added lines, base ids translated via match."""
    from witness.hunkmap import map_hunks_by_side

    sides = map_hunks_by_side(hunks, bg, hg, rename_map)
    out: dict[str, list[int]] = {}
    for h in hunks:
        ids = set(sides[h.id]["head"])
        for b in sides[h.id]["base"]:  # base ids live in the base graph: translate, never reuse
            hit = m.get(b)
            if hit is not None:
                ids.add(hit[0])
        out[h.id] = sorted(ids)
    return out


def _gname(g, nid: int) -> str:  # noqa: ANN001
    n = g.nodes[nid]
    return n.attrs.get("name") or n.key[1]


def _hunk_names(h: Hunk, bg, hg, ids) -> set[str]:  # noqa: ANN001
    """Names of nodes on the hunk's changed lines (head new range, base old range) and enclosing methods."""
    names: set[str] = set()
    for g, path, lo, hi in (
        (hg, h.new_path, h.new_start, _hunk_end(h)),
        (bg, h.old_path, h.old_start, h.old_start + max(h.old_len - 1, 0)),
    ):
        for n in g.nodes:
            if n.span and n.span[0] == path and n.span[1] <= hi and n.span[2] >= lo:
                names.add(_gname(g, n.id))
    for g, side in ((hg, "head"), (bg, "base")):
        for i in ids.get(h.id, {}).get(side, []):
            names.add(_gname(g, i))
    return names


def _fill_via_hunks(changes, hunks, bg, hg, ids):  # noqa: ANN001
    hn = {h.id: _hunk_names(h, bg, hg, ids) for h in hunks}
    out = []
    for c in changes:
        touched = {c.src, c.sink}
        if c.guard:
            touched.add(c.guard)
        for p in (c.base_path, c.head_path):
            if p:
                touched.update(x.strip() for x in p.split("->"))
        via = [h.id for h in hunks if hn[h.id] & touched]
        out.append(replace(c, via_hunks=via))
    return out


def analyze(
    repo: Path,
    ref: str | None,
    base: str | None,
    head: str | None,
    no_llm: bool,
    on_event: Callable[[dict], None],
    stages: dict | None = None,
) -> dict:
    """Run the pipeline. `stages` may override: build, flow_diff, reduce, llm, find_scope, checkout."""
    st = stages or {}
    repo = Path(repo)
    if base and head:
        info = PRInfo(
            "local",
            _git(repo, "rev-parse", base).strip(),
            _git(repo, "rev-parse", head).strip(),
            "", "",
        )
    elif ref:
        info = acquire.resolve_pr(ref, repo)
    else:
        raise EnvError("need a PR ref or --base and --head")

    diff_text = _git(repo, "diff", "-U0", "--find-renames=50%", info.base_sha, info.head_sha)
    hunks = acquire.parse_hunks(diff_text)
    rename_map = acquire.renames(diff_text)
    on_event({"type": "hunks", "hunks": [h.id for h in hunks]})

    sc = st.get("find_scope", scope_mod.find_scope)(repo, info.base_sha, info.head_sha, hunks, 2, 400)
    lang = _lang(sc.files)
    notes: list[str] = []
    changes: list[FlowChange] = []
    llm = None if no_llm else st.get("llm", _default_llm)()
    partial = False
    head_g = None
    seed_map: dict[str, list[int]] = {}
    try:
        build = st.get("build", _default_build)
        checkout = st.get("checkout", lambda sha: acquire.checkout(repo, sha, _cache(repo)))
        bg, bver = build(checkout(info.base_sha), sc.files)
        hg, hver = build(checkout(info.head_sha), sc.files)
        if bver != hver:
            raise EnvError(f"joern version mismatch: base {bver} vs head {hver}")
        rules.tag(bg, lang, None)
        rules.tag(hg, lang, None)
        from witness.match import match

        m = match(bg, hg, rename_map)
        try:
            changes = st.get("flow_diff", _default_flow_diff)(bg, hg, m)
        except NotImplementedStub:
            notes.append("flow diff unavailable")
        head_g = hg
        seed_map = _seed_map(hunks, bg, hg, m, rename_map)
        from witness.hunkmap import map_hunks_by_side

        sides = map_hunks_by_side(hunks, bg, hg, rename_map)
        changes = _fill_via_hunks(changes, hunks, bg, hg, sides)
    except JoernMissing:
        partial = True
        notes.append("joern missing: only the hunk list is available; run witness doctor")
    on_event({"type": "deep_ready", "changes": len(changes), "partial": partial})

    hunk_rows, evidence, grounded, slices = [], [], 0, {}
    for h in hunks:
        mine = [c for c in changes if h.id in c.via_hunks]
        row = {"id": h.id, "path": h.new_path or h.old_path, "start": h.new_start,
               "end": _hunk_end(h), "title": f"{h.new_path}:{h.new_start}",
               "kinds": sorted({c.kind for c in mine}), "diff": h.text,
               "explanation": [], "old_path": h.old_path, "new_path": h.new_path,
               "old_start": h.old_start, "old_len": h.old_len, "new_start": h.new_start,
               "new_len": h.new_len, "text": h.text}
        if head_g is not None:
            try:
                sl = st.get("reduce", _default_reduce)(head_g, seed_map.get(h.id, []), mine, 6000)
            except NotImplementedStub:
                sl = {}
            slices[h.id] = sl
            pack = explain_mod.build_pack(h, mine, sl)
            ex = explain_mod.explain(pack, llm)
            fid: dict[str, str] = {}
            for f in pack["facts"]:
                gid = f"F{len(evidence) + 1}"
                fid[f["id"]] = gid
                text = explain_mod._fact_sentence(f) or f"{f.get('type', 'fact')} in {h.new_path}"
                evidence.append({"id": gid, "text": text})
            rewrite = lambda s: _CITE.sub(lambda mo: fid.get(mo.group(0), mo.group(0)), s)  # noqa: E731
            row["title"] = ex.get("title") or row["title"]
            row["templated"] = bool(ex.get("templated"))
            row["explanation"] = [
                {"text": rewrite(s["text"]), "cites": [fid.get(c, c) for c in s["cites"]]}
                for s in ex["explanation"]
            ]
            if row["explanation"]:
                grounded += 1
        else:
            row["note"] = "not analysed"
        hunk_rows.append(row)

    flow = [
        {"kind": c.kind, "src": c.src, "sink": c.sink, "guard": c.guard,
         "hunks": list(c.via_hunks), "confidence": c.confidence}
        for c in changes
    ]
    look = [
        {"kind": c.kind, "text": f"{c.src} -> {c.sink}", "hunk": (c.via_hunks or [""])[0]}
        for c in changes
    ]
    report = {
        "schema": "witness.report.v1",
        "meta": {"schema": "witness/v1", "title": info.title or f"{info.base_sha[:8]}..{info.head_sha[:8]}",
                 "base": info.base_sha, "head": info.head_sha, "engine": "joern",
                 "language": lang, "files_in_scope": len(sc.files)},
        "coverage": {"unanalysed": len(sc.unanalysed), "unanalysed_files": list(sc.unanalysed),
                     "grounded": grounded, "total": len(hunks), "notes": notes, "partial": partial},
        "overview": {"look_first": look},
        "hunks": hunk_rows,
        "flow_changes": flow,
        "changes": [asdict(c) for c in changes],
        "slices": slices,
        "evidence": evidence,
    }
    from witness.render import validate_report

    validate_report(report)
    on_event({"type": "done"})
    return report


def _cache(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--absolute-git-dir").strip()) / "witness"
