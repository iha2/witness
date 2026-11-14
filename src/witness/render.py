"""Outputs (T14): renderers over the witness/v1 report dict, plus report validation.

Report shape is defined by schema/witness.report.v1.json. Renderers read only the report.
"""

import json

from witness.shared import FLOW_KINDS, WitnessError

_MARK = {
    "guard_bypassed": "!", "guard_added": "!", "added_flow": "+", "removed_flow": "-",
    "rerouted": "~", "new_caller": "+", "lost_caller": "-",
}
_LABEL = {
    "guard_bypassed": "Guard bypassed", "guard_added": "Guard added", "added_flow": "Added flow",
    "removed_flow": "Removed flow", "rerouted": "Rerouted", "new_caller": "New caller",
    "lost_caller": "Lost caller",
}
_SARIF_LEVEL = {"guard_bypassed": "error", "guard_added": "note", "removed_flow": "note",
                "lost_caller": "note"}


# ---------------------------------------------------------------- validation

def _fail(path: str, msg: str) -> None:
    raise WitnessError(f"invalid report at {path}: {msg}")


def _check(v: object, path: str, types: type | tuple[type, ...]) -> None:
    if isinstance(v, bool) and bool not in (types if isinstance(types, tuple) else (types,)):
        _fail(path, "unexpected boolean")
    if not isinstance(v, types):
        _fail(path, f"expected {types}")


def _req(d: dict, keys: list[str], path: str) -> None:
    _check(d, path, dict)
    for k in keys:
        if k not in d:
            _fail(path, f"missing {k!r}")


def _check_side(side: dict, path: str) -> None:
    _req(side, ["nodes", "edges"], path)
    for i, n in enumerate(side["nodes"]):
        _req(n, ["id", "label"], f"{path}.nodes[{i}]")
        if n.get("shape", "node") not in ("node", "source", "sink", "cond"):
            _fail(f"{path}.nodes[{i}]", "bad shape")
    for i, e in enumerate(side["edges"]):
        _req(e, ["src", "dst"], f"{path}.edges[{i}]")
        if e.get("status", "same") not in ("same", "added", "removed"):
            _fail(f"{path}.edges[{i}]", "bad status")


def _check_graph(g: dict, path: str) -> None:
    _req(g, ["root", "before", "after"], path)
    _check_side(g["before"], f"{path}.before")
    _check_side(g["after"], f"{path}.after")


def validate_report(report: dict) -> None:
    """Raise WitnessError if the report does not match witness/v1 (mirrors the JSON schema)."""
    _req(report, ["meta", "coverage", "overview", "hunks", "flow_changes", "evidence"], "$")
    _req(report["meta"], ["schema", "title", "base", "head"], "$.meta")
    if report["meta"]["schema"] != "witness/v1":
        _fail("$.meta.schema", "must be 'witness/v1'")
    _check(report["coverage"], "$.coverage", dict)
    _req(report["overview"], ["look_first"], "$.overview")
    for i, it in enumerate(report["overview"]["look_first"]):
        _req(it, ["kind", "text", "hunk"], f"$.overview.look_first[{i}]")
    if "graph" in report["overview"]:
        _check_graph(report["overview"]["graph"], "$.overview.graph")
    _check(report["hunks"], "$.hunks", list)
    for i, h in enumerate(report["hunks"]):
        p = f"$.hunks[{i}]"
        _req(h, ["id", "path", "start", "end", "title", "kinds", "explanation"], p)
        _check(h["start"], f"{p}.start", int)
        _check(h["end"], f"{p}.end", int)
        for j, s in enumerate(h["explanation"]):
            _req(s, ["text", "cites"], f"{p}.explanation[{j}]")
            if not isinstance(s["cites"], list) or not s["cites"]:
                _fail(f"{p}.explanation[{j}].cites", "every sentence needs at least one cite")
        if "graph" in h:
            _check_graph(h["graph"], f"{p}.graph")
    _check(report["flow_changes"], "$.flow_changes", list)
    for i, f in enumerate(report["flow_changes"]):
        p = f"$.flow_changes[{i}]"
        _req(f, ["kind", "src", "sink", "hunks"], p)
        if f["kind"] not in FLOW_KINDS:
            _fail(f"{p}.kind", f"unknown kind {f['kind']!r}")
    for i, e in enumerate(report["evidence"]):
        _req(e, ["id", "text"], f"$.evidence[{i}]")


# ---------------------------------------------------------------- mermaid

def _q(label: str) -> str:
    """Quote a mermaid label; quotes and pipes become entities, newlines spaces."""
    s = label.replace('"', "#quot;").replace("|", "#124;").replace("\n", " ")
    return f'"{s}"'


def _node(nid: str, label: str, shape: str) -> str:
    q = _q(label)
    return {"source": f"{nid}([{q}])", "sink": f"{nid}[({q})]",
            "cond": f"{nid}{{{q}}}"}.get(shape, f"{nid}[{q}]")


_ARROW = {"same": "-->", "added": "==>", "removed": "-.->"}


def _side_lines(side: dict, prefix: str, root: str) -> list[str]:
    ids = {n["id"]: f"{prefix}{i}" for i, n in enumerate(side["nodes"])}
    has_in = {e["dst"] for e in side["edges"]}
    lines = []
    for n in side["nodes"]:
        if n["id"] not in has_in:
            lines.append(f"  {root} --> {_node(ids[n['id']], n['label'], n.get('shape', 'node'))}")
    declared = {n["id"] for n in side["nodes"] if n["id"] not in has_in}
    byid = {n["id"]: n for n in side["nodes"]}
    for e in side["edges"]:
        if e["src"] not in ids or e["dst"] not in ids:
            continue
        arrow = _ARROW.get(e.get("status", "same"), "-->")
        if e.get("label"):
            arrow += f"|{_q(e['label'])}|"
        dst = byid[e["dst"]]
        dst_txt = _node(ids[e["dst"]], dst["label"], dst.get("shape", "node"))
        src_txt = ids[e["src"]]
        if e["src"] not in declared:
            s = byid[e["src"]]
            src_txt = _node(ids[e["src"]], s["label"], s.get("shape", "node"))
            declared.add(e["src"])
        lines.append(f"  {src_txt} {arrow} {dst_txt}")
        declared.add(e["dst"])
    return lines


def _mermaid(graph: dict) -> str:
    """One shared root, before and after branches, no subgraph or styling."""
    out = ["flowchart TD", f"  R([{_q(graph['root'])}]) --- B[\"before\"]", "  R --- A[\"after\"]"]
    out += _side_lines(graph["before"], "b", "B")
    out += _side_lines(graph["after"], "a", "A")
    return "```mermaid\n" + "\n".join(out) + "\n```"


# ---------------------------------------------------------------- markdown

def _cell(s: object) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _range(h: dict) -> str:
    return f"{h['path']}:{h['start']}-{h['end']}"


def _fence(text: str) -> str:
    return "```diff\n" + text.rstrip("\n") + "\n```"


def to_markdown(report: dict) -> str:
    m = report["meta"]
    ref = f"{m.get('repo', '')}#{m['pr']}" if "pr" in m else m.get("repo", "")
    head = f"# Witness report · {ref} \"{m['title']}\"".replace("·  ", "· ")
    hunks = report["hunks"]
    flowing = [h for h in hunks if h["kinds"]]
    parts = [head, "", f"`base {m['base']} → head {m['head']}` · {len(hunks)} hunks · "
             f"{len(flowing)} change data flow · engine: {m.get('engine', '?')} "
             f"({m.get('language', '?')}) · {m.get('files_in_scope', '?')} files in scope",
             "", "---", "", "## Look here first", ""]
    parts += ["| | Change | Path | Hunk |", "|---|---|---|---|"]
    for it in report["overview"]["look_first"]:
        mark = _MARK.get(it["kind"], "·")
        parts.append(f"| **{mark}** | {_cell(_LABEL.get(it['kind'], it['kind']))} | "
                     f"{_cell(it['text'])} | [`{it['hunk']}`](#{it['hunk']}) |")
    dc = report.get("description_check")
    if dc:
        parts += ["", "## Description check", ""]
        parts += [f"- ✗ **Described, not found:** {t}" for t in dc.get("described_not_found", [])]
        for t in dc.get("found_not_described", []):
            ref = f" (hunk `{t['hunk']}`)" if t.get("hunk") else ""
            parts.append(f"- ✗ **Found, not described:** {t['text']}{ref}")
    parts += ["", "## How the data flow changes", ""]
    if "graph" in report["overview"]:
        parts += ["Before on the left, after on the right. A dashed edge was removed and a bold "
                  "edge is new.", "", _mermaid(report["overview"]["graph"])]
    else:
        parts.append("No overview graph.")
    parts += ["", "---", "", "## Hunks", ""]
    for h in flowing:
        marks = " · ".join(f"**{_MARK.get(k, '·')}** {k.replace('_', ' ')}" for k in h["kinds"])
        parts += [f"### `{h['id']}` · {h['title']}", "", f"{marks} · `{_range(h)}`", ""]
        if h.get("diff"):
            parts += [_fence(h["diff"]), ""]
        if "graph" in h:
            parts += [_mermaid(h["graph"]), ""]
        parts += [_explanation(h), ""]
    plain = [h for h in hunks if not h["kinds"]]
    if plain:
        parts += ["### No flow change", "", "| Hunk | Where | What changed |", "|---|---|---|"]
        for h in plain:
            parts.append(f"| `{h['id']}` | `{_cell(_range(h))}` | {_cell(h['title'])} |")
        parts.append("")
    parts += ["---", "", "## Evidence", "", "| Id | Fact |", "|---|---|"]
    parts += [f"| {e['id']} | {_cell(e['text'])} |" for e in report["evidence"]]
    cov = report["coverage"]
    parts += ["", "## Coverage", ""]
    if cov.get("unanalysed"):
        parts.append(f"- {cov['unanalysed']} neighbouring files were not analysed.")
    if "grounded" in cov:
        parts.append(f"- Explanations: {m.get('model', 'templated')}. {cov['grounded']} of "
                     f"{cov.get('total', len(hunks))} are grounded in the evidence above.")
    parts += [f"- {n}" for n in cov.get("notes", [])]
    return "\n".join(parts) + "\n"


def _explanation(h: dict) -> str:
    if not h["explanation"]:
        return h.get("note", "")
    return " ".join(f"{s['text']} **[{', '.join(s['cites'])}]**" for s in h["explanation"])


# ---------------------------------------------------------------- text

def to_text(report: dict) -> str:
    """Plain terminal text: numbered changed-path list with +/- markers."""
    m = report["meta"]
    lines = [f"Witness report: {m['title']}  ({m['base']} -> {m['head']})", ""]
    for i, f in enumerate(report["flow_changes"], 1):
        mark = _MARK.get(f["kind"], "·")
        via = ", ".join(f["hunks"])
        guard = f" [guard {f['guard']}]" if f.get("guard") else ""
        lines.append(f"{i}. {mark} {_LABEL.get(f['kind'], f['kind'])}: "
                     f"{f['src']} -> {f['sink']}{guard}  (hunk {via})")
        for s in f.get("head_steps", []):
            lines.append(f"     + {s['path']}:{s['line']}  {s['text']}")
    if not report["flow_changes"]:
        lines.append("No data-flow changes.")
    lines += ["", "Hunks:"]
    for h in report["hunks"]:
        lines.append(f"  {h['id']}  {_range(h)}  {h['title']}")
        for s in h["explanation"]:
            lines.append(f"    {s['text']} [{', '.join(s['cites'])}]")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- sarif

def to_sarif(report: dict) -> dict:
    results = []
    for f in report["flow_changes"]:
        loc = {"physicalLocation": {
            "artifactLocation": {"uri": f.get("path", "")},
            "region": {"startLine": max(int(f.get("line", 1)), 1)}}}
        res: dict = {
            "ruleId": f["kind"],
            "level": _SARIF_LEVEL.get(f["kind"], "warning"),
            "message": {"text": f"{_LABEL.get(f['kind'], f['kind'])}: {f['src']} -> {f['sink']}"},
            "locations": [loc],
        }
        steps = f.get("head_steps") or []
        if steps:
            res["codeFlows"] = [{"threadFlows": [{"locations": [
                {"location": {
                    "physicalLocation": {"artifactLocation": {"uri": s["path"]},
                                         "region": {"startLine": max(int(s["line"]), 1)}},
                    "message": {"text": s["text"]}}}
                for s in steps]}]}]
        results.append(res)
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{
            "tool": {"driver": {
                "name": "witness",
                "rules": [{"id": k, "shortDescription": {"text": _LABEL[k]}} for k in FLOW_KINDS],
            }},
            "results": results,
        }],
    }


# ---------------------------------------------------------------- annotations

def to_annotations(report: dict) -> str:
    """Hunk-keyed JSONL, one line per hunk."""
    rows = []
    for h in report["hunks"]:
        rows.append(json.dumps({
            "hunk_id": h["id"], "path": h["path"], "start": h["start"], "end": h["end"],
            "title": h["title"], "kinds": h["kinds"],
            "body": " ".join(f"{s['text']} [{', '.join(s['cites'])}]" for s in h["explanation"]),
        }, sort_keys=True))
    return "\n".join(rows) + ("\n" if rows else "")
