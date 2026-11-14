"""Function matcher (T8): base-to-head node matching in tiers (design section 6).

Tiers, each run only over what earlier tiers left unmatched:
1. exact stable key, base path mapped through the rename map -> "exact" 1.0
2. same path and qname, different signature (METHOD) -> "changed_signature" 0.9
3. same body fingerprint (attrs["fingerprint"]), e.g. move or rename -> "fingerprint" 0.85
4. structural fallback for methods in the same or a renamed file -> "structural"
5. sub-method nodes inside matched methods by (kind, name, ordinal) -> "ordinal" 0.8

Every head node is assigned at most once.
"""

from collections import defaultdict
from difflib import SequenceMatcher

from witness.model import Graph, Node
from witness.shared import Match

METHOD = "METHOD"
STRUCTURAL_MIN = 0.6


def _fp(n: Node) -> str:
    return n.attrs.get("fingerprint", "")


def _name(n: Node) -> str:
    return n.attrs.get("name") or n.key[1]


def _owner(g: Graph, n: Node, methods_by_path: dict[str, list[Node]]) -> int | None:
    """Innermost METHOD whose span contains n (same file)."""
    if n.span is None:
        return None
    path, lo, hi = n.span
    best: Node | None = None
    for m in methods_by_path.get(path, ()):
        if m.span is None or m.id == n.id:
            continue
        if m.span[1] <= lo and hi <= m.span[2]:
            if best is None or (m.span[2] - m.span[1]) < (best.span[2] - best.span[1]):  # type: ignore[union-attr]
                best = m
    return best.id if best else None


def match(base: Graph, head: Graph, renames: dict[str, str]) -> Match:
    result: Match = {}
    used_head: set[int] = set()

    def assign(b: int, h: int, how: str, conf: float) -> None:
        result[b] = (h, how, conf)
        used_head.add(h)

    def mp(path: str) -> str:
        return renames.get(path, path)

    # Tier 1: exact key (with multiplicity, paired in node order).
    head_by_key: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for n in head.nodes:
        head_by_key[tuple(n.key)].append(n.id)  # type: ignore[index]
    for n in base.nodes:
        p, q, s, x = n.key
        cands = head_by_key.get((mp(p), q, s, x))
        while cands and cands[0] in used_head:
            cands.pop(0)
        if cands:
            assign(n.id, cands.pop(0), "exact", 1.0)

    def free(g: Graph, matched: set[int], kind: str = METHOD) -> list[Node]:
        return [n for n in g.nodes if n.kind == kind and n.id not in matched]

    def unmatched_base() -> list[Node]:
        return free(base, set(result))

    def unmatched_head() -> list[Node]:
        return free(head, used_head)

    # Tier 2: signature drift.
    hmap: dict[tuple[str, str], list[Node]] = defaultdict(list)
    for h in unmatched_head():
        hmap[(h.key[0], h.key[1])].append(h)
    for b in unmatched_base():
        cands = hmap.get((mp(b.key[0]), b.key[1]), [])
        cands = [c for c in cands if c.id not in used_head]
        if cands:
            assign(b.id, cands[0].id, "changed_signature", 0.9)

    # Tier 3: body fingerprint (renames and moves across files).
    hfp: dict[str, list[Node]] = defaultdict(list)
    for h in unmatched_head():
        if _fp(h):
            hfp[_fp(h)].append(h)
    for b in unmatched_base():
        if not _fp(b):
            continue
        cands = [c for c in hfp.get(_fp(b), []) if c.id not in used_head]
        if not cands:
            continue
        same_name = [c for c in cands if c.key[1] == b.key[1]]
        pick = (same_name or cands)[0]
        conf = 0.85 if len(cands) == 1 else 0.7
        assign(b.id, pick.id, "fingerprint", conf)

    # Tier 4: structural fallback within the same (renamed) file.
    hby_path: dict[str, list[Node]] = defaultdict(list)
    for h in unmatched_head():
        hby_path[h.key[0]].append(h)
    scored: list[tuple[float, int, int]] = []
    for b in unmatched_base():
        for h in hby_path.get(mp(b.key[0]), []):
            sim = SequenceMatcher(None, b.key[1], h.key[1]).ratio()
            if b.span and h.span:
                lb = max(b.span[2] - b.span[1], 1)
                lh = max(h.span[2] - h.span[1], 1)
                sim = 0.7 * sim + 0.3 * (min(lb, lh) / max(lb, lh))
            if sim >= STRUCTURAL_MIN:
                scored.append((sim, b.id, h.id))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    for sim, b, h in scored:
        if b not in result and h not in used_head:
            assign(b, h, "structural", round(sim * 0.7, 3))

    # Tier 5: sub-method nodes inside matched methods by (kind, name, ordinal).
    bm: dict[str, list[Node]] = defaultdict(list)
    hm: dict[str, list[Node]] = defaultdict(list)
    for n in base.nodes:
        if n.kind == METHOD and n.span:
            bm[n.span[0]].append(n)
    for n in head.nodes:
        if n.kind == METHOD and n.span:
            hm[n.span[0]].append(n)
    groups_b: dict[tuple[int, str, str], list[int]] = defaultdict(list)
    groups_h: dict[tuple[int, str, str], list[int]] = defaultdict(list)
    for n in base.nodes:
        if n.kind == METHOD or n.id in result:
            continue
        o = _owner(base, n, bm)
        if o is not None and o in result:
            groups_b[(result[o][0], n.kind, _name(n))].append(n.id)
    for n in head.nodes:
        if n.kind == METHOD or n.id in used_head:
            continue
        o = _owner(head, n, hm)
        if o is not None:
            groups_h[(o, n.kind, _name(n))].append(n.id)
    for gk, bids in groups_b.items():
        hids = [h for h in groups_h.get(gk, []) if h not in used_head]
        for b, h in zip(bids, hids):
            assign(b, h, "ordinal", 0.8)

    return result
