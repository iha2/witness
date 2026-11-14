"""Description check (T12): compare a PR description's claims with the detected flow changes."""

import hashlib
import json
from collections.abc import Callable

from witness.shared import FlowChange, Hunk, NotImplementedStub


def change_id(c: FlowChange) -> str:
    """Stable 10-hex id for a flow change."""
    return hashlib.sha1(f"{c.kind}|{c.src}|{c.sink}".encode()).hexdigest()[:10]


def _result(reason: str | None, nf: list[str] | None = None, fnd: list[str] | None = None) -> dict:
    out: dict = {"described_not_found": nf or [], "found_not_described": fnd or []}
    if reason:
        out["reason"] = reason
    return out


def _prompt(title: str, body: str, facts: list[dict]) -> str:
    return (
        "You compare a pull request description with detected data-flow changes.\n"
        "List each distinct behavioural claim in the description. For each claim, list the ids "
        "of the changes that support it (empty list if none). Use only ids from CHANGES.\n"
        'Reply with JSON only: {"claims": [{"text": "...", "matches": ["id"]}]}\n\n'
        f"TITLE: {title}\nBODY:\n{body}\n\nCHANGES:\n{json.dumps(facts, indent=1)}\n"
    )


def _parse(raw: str) -> list[dict] | None:
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        data = json.loads(raw[start:end])
    except (ValueError, TypeError):
        return None
    claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(claims, list):
        return None
    out = []
    for c in claims:
        if isinstance(c, dict) and isinstance(c.get("text"), str) and c["text"].strip():
            m = c.get("matches")
            out.append({"text": c["text"].strip(), "matches": [x for x in m if isinstance(x, str)] if isinstance(m, list) else []})
    return out


def _default_validate(expl: dict, pack: dict) -> list[str]:
    from witness import explain

    try:
        return explain.validate(expl, pack)
    except NotImplementedStub:
        return []


def check(
    title: str,
    body: str,
    changes: list[FlowChange],
    hunks: list[Hunk],
    llm: Callable[[str], str] | None,
    validate: Callable[[dict, dict], list[str]] | None = None,
) -> dict:
    """Return {"described_not_found": [...], "found_not_described": [ids], "reason"?: str}.

    A claim whose cited change ids fail validation counts as not found.
    """
    if not (title or "").strip() and not (body or "").strip():
        return _result("empty description")
    if llm is None:
        return _result("no llm available; description not checked")
    # Facts use the explain.build_pack shape: each has "id" and "type" (the guard kinds are
    # their own type, every other change is "flow_change").
    facts = [
        {"id": change_id(c),
         "type": c.kind if c.kind in ("guard_bypassed", "guard_added") else "flow_change",
         "kind": c.kind, "src": c.src, "sink": c.sink, "guard": c.guard or "",
         "hunks": list(c.via_hunks)}
        for c in changes
    ]
    try:
        claims = _parse(llm(_prompt(title, body, facts)))
    except Exception:  # noqa: BLE001 - any llm failure degrades to "not checked"
        return _result("llm call failed; description not checked")
    if claims is None:
        return _result("llm reply was not valid json; description not checked")
    known = {f["id"] for f in facts}
    pack = {
        "hunk": {"id": "", "path": "", "text": "\n".join(h.text for h in hunks)},
        "facts": facts,
        "summaries": {},
        "coverage": {},
    }
    check_fn = validate or _default_validate
    matched: set[str] = set()
    not_found: list[str] = []
    for claim in claims:
        ids = [i for i in claim["matches"] if i in known]
        if ids and check_fn({"explanation": [{"text": claim["text"], "cites": ids}]}, pack):
            ids = []
        if ids:
            matched.update(ids)
        else:
            not_found.append(claim["text"])
    return _result(
        None,
        not_found,
        [f["id"] for f in facts if f["id"] not in matched],
    )
