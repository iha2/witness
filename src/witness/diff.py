"""Flow diff (T9, design section 7).

Value flows run source -> sink over dflow/arg/ret edges, at most DEPTH_CAP edges
long and at most PATH_CAP sink-ending paths per source. Endpoints are compared
through the match: a matched node is identified by its head id, an unmatched one
by its side and own id, so renames produce no change.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from witness.model import Graph
from witness.shared import FLOW_KINDS, FlowChange, Match

FLOW_EDGES = {"dflow", "arg", "ret"}
DEPTH_CAP = 7
PATH_CAP = 200
STEP_CAP = 20000
CAP_PENALTY = 0.8

Canon = tuple[str, int]


@dataclass
class _Pair:
    paths: list[tuple[Canon, ...]] = field(default_factory=list)
    capped: bool = False


@dataclass
class _Side:
    pairs: dict[tuple[Canon, Canon], _Pair]
    names: dict[Canon, str]
    guards: set[Canon]
    conf: dict[Canon, float]
    calls: set[tuple[Canon, Canon]]


def _name(g: Graph, nid: int) -> str:
    n = g.nodes[nid]
    return n.attrs.get("name") or n.key[1]


def _analyze(g: Graph, canon: dict[int, Canon], conf: dict[Canon, float]) -> _Side:
    adj: dict[int, list[int]] = defaultdict(list)
    calls: set[tuple[Canon, Canon]] = set()
    for s, d, k in g.edges:
        if k in FLOW_EDGES:
            adj[s].append(d)
        elif k == "calls":
            calls.add((canon[s], canon[d]))
    for lst in adj.values():
        lst.sort()
    role = {n.id: n.attrs.get("role", "") for n in g.nodes}
    sinks = {i for i, r in role.items() if r == "sink"}
    pairs: dict[tuple[Canon, Canon], _Pair] = {}

    for src in sorted(i for i, r in role.items() if r == "source"):
        found = 0
        steps = 0
        capped = False
        path = [src]
        on_path = {src}
        # iterative DFS: stack of (node, next-neighbour index)
        stack: list[tuple[int, int]] = [(src, 0)]
        while stack and not capped:
            node, idx = stack.pop()
            nbrs = adj.get(node, ())
            if idx >= len(nbrs):
                on_path.discard(node)
                path.pop()
                continue
            stack.append((node, idx + 1))
            nxt = nbrs[idx]
            if nxt in on_path or len(path) > DEPTH_CAP:
                continue
            steps += 1
            if steps > STEP_CAP:
                capped = True
                break
            path.append(nxt)
            on_path.add(nxt)
            stack.append((nxt, 0))
            if nxt in sinks:
                pr = pairs.setdefault((canon[src], canon[nxt]), _Pair())
                pr.paths.append(tuple(canon[i] for i in path))
                found += 1
                if found >= PATH_CAP:
                    capped = True
        if capped:
            for (cs, _ct), pr in pairs.items():
                if cs == canon[src]:
                    pr.capped = True
    names = {canon[n.id]: _name(g, n.id) for n in g.nodes}
    guards = {canon[i] for i, r in role.items() if r == "guard"}
    return _Side(pairs, names, guards, conf, calls)


def _base_canon(base: Graph, m: Match) -> tuple[dict[int, Canon], dict[Canon, float]]:
    canon: dict[int, Canon] = {}
    conf: dict[Canon, float] = {}
    for n in base.nodes:
        if n.id in m:
            h, _how, c = m[n.id]
            canon[n.id] = ("h", h)
            conf[("h", h)] = c
        else:
            canon[n.id] = ("b", n.id)
    return canon, conf


def _head_canon(head: Graph, m: Match) -> tuple[dict[int, Canon], dict[Canon, float]]:
    return {n.id: ("h", n.id) for n in head.nodes}, {}


def _fmt(side: _Side, path: tuple[Canon, ...]) -> str:
    return " -> ".join(side.names.get(c, "?") for c in path)


def _shortest(pr: _Pair) -> tuple[Canon, ...]:
    return min(pr.paths, key=lambda p: (len(p), p))


def _interior(path: tuple[Canon, ...]) -> frozenset[Canon]:
    return frozenset(path[1:-1])


def _common_guards(side: _Side, pr: _Pair) -> set[Canon]:
    sets = [set(p[1:-1]) & side.guards for p in pr.paths]
    return set.intersection(*sets) if sets else set()


def _avoiding(pr: _Pair, g: Canon) -> tuple[Canon, ...] | None:
    ok = [p for p in pr.paths if g not in p[1:-1]]
    return min(ok, key=lambda p: (len(p), p)) if ok else None


def flow_diff(base: Graph, head: Graph, m: Match) -> list[FlowChange]:
    bc, bconf = _base_canon(base, m)
    hc, _ = _head_canon(head, m)
    b = _analyze(base, bc, bconf)
    h = _analyze(head, hc, {})
    names = {**b.names, **h.names}
    out: list[FlowChange] = []

    def conf_of(cs: Canon, ct: Canon, capped: bool) -> float:
        c = min(b.conf.get(cs, 1.0), b.conf.get(ct, 1.0))
        return round(c * (CAP_PENALTY if capped else 1.0), 4)

    def add(kind: str, cs: Canon, ct: Canon, guard: Canon | None,
            bp: tuple[Canon, ...] | None, hp: tuple[Canon, ...] | None, capped: bool) -> None:
        out.append(FlowChange(
            kind=kind,
            src=names[cs],
            sink=names[ct],
            guard=names[guard] if guard is not None else None,
            base_path=_fmt(b, bp) if bp else None,
            head_path=_fmt(h, hp) if hp else None,
            via_hunks=[],
            confidence=conf_of(cs, ct, capped),
        ))

    for key in sorted(set(b.pairs) | set(h.pairs)):
        cs, ct = key
        bp, hp = b.pairs.get(key), h.pairs.get(key)
        if bp is None and hp is not None:
            add("added_flow", cs, ct, None, None, _shortest(hp), hp.capped)
            continue
        if hp is None and bp is not None:
            add("removed_flow", cs, ct, None, _shortest(bp), None, bp.capped)
            continue
        assert bp is not None and hp is not None
        capped = bp.capped or hp.capped
        flagged = False
        for g in sorted(_common_guards(b, bp)):
            alt = _avoiding(hp, g)
            if alt is not None:
                add("guard_bypassed", cs, ct, g, _shortest(bp), alt, capped)
                flagged = True
        for g in sorted(_common_guards(h, hp)):
            alt = _avoiding(bp, g)
            if alt is not None:
                add("guard_added", cs, ct, g, alt, _shortest(hp), capped)
                flagged = True
        if not flagged:
            sb, sh = _shortest(bp), _shortest(hp)
            if _interior(sb) != _interior(sh):
                add("rerouted", cs, ct, None, sb, sh, capped)

    # Caller deltas into methods present on both sides.
    shared = {c for c in bc.values() if c[0] == "h"}
    for (cs, cd) in sorted(h.calls - b.calls):
        if cd in shared:
            out.append(_call("new_caller", names[cs], names[cd], b, h, cs, cd))
    for (cs, cd) in sorted(b.calls - h.calls):
        if cd in shared:
            out.append(_call("lost_caller", names[cs], names[cd], b, h, cs, cd))

    rank = {k: i for i, k in enumerate(FLOW_KINDS)}
    out.sort(key=lambda c: (rank[c.kind], c.src, c.sink, c.guard or "",
                            c.base_path or "", c.head_path or ""))
    return out


def _call(kind: str, src: str, sink: str, b: _Side, h: _Side, cs: Canon, cd: Canon) -> FlowChange:
    c = min(b.conf.get(cs, 1.0), b.conf.get(cd, 1.0))
    return FlowChange(kind, src, sink, None, None, None, [], round(c, 4))
