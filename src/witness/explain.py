"""Explainer and validator (T11): evidence packs, grounded explanations (design section 10).

Slice input (T10 `reduce_slice` output, read tolerantly):
  {"nodes": [{"name", "span", "role"?}], "edges": [...], "truncated": bool, "dropped": int,
   "summaries"?: {name: str}, "unanalysed"?: int}
A node with role "enclosing" becomes an enclosing fact, role "caller" a caller fact.
"""

import json
import keyword
import re
from collections.abc import Callable
from pathlib import Path

from witness.shared import FLOW_KINDS, FlowChange, Hunk

MAX_PACK_TOKENS = 6000
MAX_HUNK_CHARS = 8000
_PROMPT = Path(__file__).parent / "prompts" / "explain.v1.md"

# Claim phrase -> fact types (or "flow_change:<kind>") that back it.
_CLAIMS: tuple[tuple[re.Pattern[str], str, frozenset[str]], ...] = (
    (re.compile(r"\bbypass(?:es|ed|ing)?\b", re.I), "bypasses", frozenset({"guard_bypassed"})),
    (re.compile(r"\breach(?:es|ed)?\b", re.I), "reaches",
     frozenset({"flow_change:added_flow", "flow_change:rerouted", "guard_bypassed"})),
    (re.compile(r"\bnow calls?\b", re.I), "now calls",
     frozenset({"flow_change:new_caller", "flow_change:added_flow", "caller"})),
)

_IDENT = r"[A-Za-z_][\w.:#]*"
_CALL_RE = re.compile(rf"({_IDENT})\(")
_TICK_RE = re.compile(r"`([^`]+)`")
_NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_CITE_RE = re.compile(r"\[F\d+\]")

_TITLES = {"guard_bypassed": "A guard is bypassed", "guard_added": "A guard is added"}


def _size(pack: dict) -> int:
    return len(json.dumps(pack, sort_keys=True)) // 4


def build_pack(hunk: Hunk, changes: list[FlowChange], slice_: dict) -> dict:
    """Deterministic evidence pack for one hunk, at most 6k tokens (len/4)."""
    facts: list[dict] = []

    def add(**f: object) -> None:
        facts.append({"id": f"F{len(facts) + 1}", **f})

    nodes = [n for n in (slice_.get("nodes") or []) if isinstance(n, dict)]
    for n in nodes:
        if n.get("role") == "enclosing":
            add(type="enclosing", node=str(n.get("name", "")), span=str(n.get("span", "")))
    mine = [c for c in changes if hunk.id in c.via_hunks]
    mine.sort(key=lambda c: FLOW_KINDS.index(c.kind) if c.kind in FLOW_KINDS else len(FLOW_KINDS))
    for c in mine:
        if c.kind in _TITLES:
            add(type=c.kind, guard=c.guard or "", src=c.src, sink=c.sink)
        else:
            add(type="flow_change", kind=c.kind, src=c.src, sink=c.sink,
                base_path=c.base_path or "", head_path=c.head_path or "")
    for n in nodes:
        if n.get("role") == "caller":
            add(type="caller", node=str(n.get("name", "")), span=str(n.get("span", "")))

    end = hunk.new_start + max(hunk.new_len - 1, 0)
    pack = {
        "hunk": {"id": hunk.id, "path": hunk.new_path, "new_range": [hunk.new_start, end],
                 "text": hunk.text[:MAX_HUNK_CHARS]},
        "facts": facts,
        "summaries": {str(k): str(v) for k, v in (slice_.get("summaries") or {}).items()},
        "coverage": {
            "engine": "joern",
            "unanalysed_neighbours": int(slice_.get("unanalysed", 0) or 0),
            "truncated": bool(slice_.get("truncated", False)),
            "dropped": int(slice_.get("dropped", 0) or 0),
        },
    }
    # Shrink deterministically until under budget: summaries, trailing facts, then hunk text.
    while _size(pack) > MAX_PACK_TOKENS:
        if pack["summaries"]:
            pack["summaries"].pop(sorted(pack["summaries"])[-1])
        elif len(pack["facts"]) > 1:
            pack["facts"].pop()
        elif len(pack["hunk"]["text"]) > 200:
            pack["hunk"]["text"] = pack["hunk"]["text"][: len(pack["hunk"]["text"]) // 2]
        else:
            break
    return pack


def _strings(x: object) -> list[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [s for v in x.values() for s in _strings(v)]
    if isinstance(x, list):
        return [s for v in x for s in _strings(v)]
    return []


def _known_text(pack: dict) -> str:
    parts = [pack.get("hunk", {}).get("text", "")]
    parts += _strings(pack.get("facts", []))
    parts += _strings(pack.get("summaries", {}))
    return "\n".join(parts)


def _identifiers(text: str) -> list[str]:
    found: list[str] = []
    for m in _TICK_RE.finditer(text):
        found += re.findall(_IDENT, m.group(1))
    found += _CALL_RE.findall(text)
    out: list[str] = []
    for f in found:
        f = f.rstrip(".:#")
        if f and f not in out and not keyword.iskeyword(f) and f not in ("None", "True", "False"):
            out.append(f)
    return out


def _seen(token: str, blob: str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(token)}(?![\w])", blob) is not None


def validate(expl: dict, pack: dict) -> list[str]:
    """Deterministic grounding check. Returns error codes; empty means grounded."""
    errors: list[str] = []

    def err(e: str) -> None:
        if e not in errors:
            errors.append(e)

    sentences = expl.get("explanation") if isinstance(expl, dict) else None
    if not isinstance(sentences, list) or not sentences:
        return ["bad-shape"]
    facts = {f["id"]: f for f in pack.get("facts", [])}
    blob = _known_text(pack)

    def check_text(text: str) -> None:
        for ident in _identifiers(text):
            if not _seen(ident, blob):
                err(f"unknown-identifier:{ident}")
        for num in _NUM_RE.findall(_CITE_RE.sub("", text)):
            if not _seen(num, blob):
                err(f"unknown-number:{num}")

    if isinstance(expl.get("title"), str):
        check_text(expl["title"])
    for s in sentences:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str):
            err("bad-shape")
            continue
        cites = s.get("cites")
        if not isinstance(cites, list) or not cites:
            err("no-cite")
            cites = []
        cited: list[dict] = []
        for c in cites:
            if isinstance(c, str) and c in facts:
                cited.append(facts[c])
            else:
                err(f"bad-cite:{c}")
        check_text(s["text"])
        backing = {f["type"] for f in cited} | {
            f"flow_change:{f['kind']}" for f in cited if f["type"] == "flow_change"}
        for pat, name, allowed in _CLAIMS:
            if pat.search(s["text"]) and not backing & allowed:
                err(f"unbacked-flow-claim:{name}")
    return errors


def _fact_sentence(f: dict) -> str | None:
    t = f["type"]
    if t == "enclosing":
        return f"The hunk is inside `{f['node']}` ({f['span']})."
    if t == "guard_bypassed":
        return f"Guard `{f['guard']}` is bypassed between `{f['src']}` and `{f['sink']}`."
    if t == "guard_added":
        return f"Guard `{f['guard']}` is added between `{f['src']}` and `{f['sink']}`."
    if t == "flow_change":
        return f"Flow change ({f['kind']}) from `{f['src']}` to `{f['sink']}`."
    if t == "caller":
        return f"`{f['node']}` is a caller ({f['span']})."
    return None


def _templated(pack: dict) -> dict:
    """Explanation rendered straight from the facts; cites every sentence."""
    facts = pack.get("facts", [])
    sentences = []
    for f in facts:
        text = _fact_sentence(f)
        if text:
            sentences.append({"text": text, "cites": [f["id"]]})
    title = f"Change in {pack.get('hunk', {}).get('path', 'file')}"
    for f in facts:
        if f["type"] in _TITLES:
            title = _TITLES[f["type"]]
            break
        if f["type"] == "flow_change":
            title = f"Data flow changed ({f['kind']})"
            break
    return {"title": title, "explanation": sentences, "templated": True}


def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def _prompt(pack: dict, repair: str = "") -> str:
    shown = {**pack, "hunk": {k: v for k, v in pack["hunk"].items() if k != "text"}}
    values = {
        "HUNK_BLOCK": _fence(pack["hunk"]["text"]),
        "PACK_BLOCK": _fence(json.dumps(shown, indent=1, sort_keys=True)),
        "REPAIR": repair,
    }
    # Single pass, so placeholder-looking text inside the hunk is never re-substituted.
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)),
                  _PROMPT.read_text())


def _parse(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def explain(pack: dict, llm: Callable[[str], str] | None) -> dict:
    """LLM explanation with one repair round; templated from facts if still invalid."""
    if llm is None:
        return _templated(pack)
    repair = ""
    for _ in range(2):
        try:
            parsed = _parse(llm(_prompt(pack, repair)))
        except Exception:
            return _templated(pack)
        errors = validate(parsed, pack) if parsed is not None else ["bad-json"]
        if not errors and parsed is not None:
            return {"title": str(parsed.get("title", "")),
                    "explanation": parsed["explanation"], "templated": False}
        repair = ("\nYour previous answer failed validation: " + ", ".join(errors)
                  + ". Reply again with corrected JSON only.\n")
    return _templated(pack)
