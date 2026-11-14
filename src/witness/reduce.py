"""Slice reducer (T10, design section 9).

Output node shape (consumed by explain.build_pack):
  {"id", "name", "span", "role": "enclosing" | "caller" | "related"}
Result: {"nodes", "edges", "truncated", "dropped", "rolled_up", "unanalysed"}.
Flow nodes are kept only on a path from a seed to a node named by a change (no filter when
there are no changes). Nodes beyond the budget are rolled up by file in "rolled_up".
"""

from collections import deque

from witness.model import Graph
from witness.shared import FLOW_KINDS, FlowChange

DEPTH = 7
_FLOW = {"dflow", "arg", "ret"}


def _bfs(
    adj: dict[int, list[int]],
    seeds: list[int],
    depth: int,
    dist: dict[int, int],
    parent: dict[int, int] | None = None,
) -> None:
    q = deque((s, 0) for s in seeds)
    seen = set(seeds)
    while q:
        cur, d = q.popleft()
        if d >= depth:
            continue
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                if parent is not None:
                    parent[nxt] = cur
                dist[nxt] = min(dist.get(nxt, d + 1), d + 1)
                q.append((nxt, d + 1))


def _name(g: Graph, nid: int) -> str:
    n = g.nodes[nid]
    return n.attrs.get("name") or n.key[1] or n.key[3] or str(nid)


def reduce_slice(
    head: Graph,
    seeds: list[int],
    changes: list[FlowChange],
    budget: int,
) -> dict:
    seeds = [s for s in dict.fromkeys(seeds) if 0 <= s < len(head.nodes)]
    calls_in: dict[int, list[int]] = {}
    both: dict[int, list[int]] = {}
    flow_out: dict[int, list[int]] = {}
    flow_in: dict[int, list[int]] = {}
    for s, d, k in head.edges:
        if k == "calls":
            calls_in.setdefault(d, []).append(s)
            both.setdefault(s, []).append(d)
            both.setdefault(d, []).append(s)
        elif k in _FLOW:
            flow_out.setdefault(s, []).append(d)
            flow_in.setdefault(d, []).append(s)

    dist: dict[int, int] = {s: 0 for s in seeds}
    hop1: dict[int, int] = {}
    _bfs(both, seeds, 1, hop1)
    hops = 1 if len(set(hop1) | set(seeds)) >= 5 else 2
    calls_d: dict[int, int] = {}
    _bfs(both, seeds, hops, calls_d)
    flow_d: dict[int, int] = {}
    fparent: dict[int, int] = {}
    _bfs(flow_out, seeds, DEPTH, flow_d, fparent)
    bd: dict[int, int] = {}
    bparent: dict[int, int] = {}
    _bfs(flow_in, seeds, DEPTH, bd, bparent)
    for n, d in bd.items():
        flow_d[n] = min(flow_d.get(n, d), d)
    changed_names = {nm for c in changes for nm in (c.src, c.sink, c.guard) if nm}
    if changed_names:
        # Keep only flow nodes on a path from a seed to a node named by a change.
        keep_flow: set[int] = set()
        for parent in (fparent, bparent):
            for n in parent:
                if _name(head, n) in changed_names:
                    while n in parent and n not in keep_flow:
                        keep_flow.add(n)
                        n = parent[n]
        flow_d = {n: d for n, d in flow_d.items() if n in keep_flow}
    for src in (calls_d, flow_d):
        for n, d in src.items():
            dist[n] = min(dist.get(n, d), d)

    rank_of: dict[str, int] = {}
    for c in changes:
        r = FLOW_KINDS.index(c.kind) if c.kind in FLOW_KINDS else len(FLOW_KINDS)
        for nm in (c.src, c.sink, c.guard):
            if nm:
                rank_of[nm] = min(rank_of.get(nm, r), r)

    seed_set = set(seeds)
    callers = {s for t in seed_set for s in calls_in.get(t, [])} - seed_set
    names = {n: _name(head, n) for n in dist}

    def order(n: int) -> tuple:
        return (n not in seed_set, rank_of.get(names[n], len(FLOW_KINDS) + 1), dist[n], n)

    ranked = sorted(dist, key=order)
    kept = ranked[: max(budget, 0)]
    dropped = len(ranked) - len(kept)
    rolled_up: dict[str, int] = {}  # the dropped tail, rolled up by file
    for n in ranked[len(kept):]:
        node = head.nodes[n]
        f = node.span[0] if node.span else node.key[0]
        rolled_up[f] = rolled_up.get(f, 0) + 1
    keep_set = set(kept)
    nodes = []
    for n in kept:
        node = head.nodes[n]
        role = "enclosing" if n in seed_set else "caller" if n in callers else "related"
        span = f"{node.span[0]}:{node.span[1]}-{node.span[2]}" if node.span else ""
        nodes.append({"id": n, "name": names[n], "span": span, "role": role})
    edges = [
        {"src": s, "dst": d, "kind": k}
        for s, d, k in head.edges
        if s in keep_set and d in keep_set
    ]
    unanalysed = sum(1 for n in ranked if head.nodes[n].kind == "EXTERNAL")
    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": dropped > 0,
        "dropped": dropped,
        "rolled_up": rolled_up,
        "unanalysed": unanalysed,
    }
