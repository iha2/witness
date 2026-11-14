"""Tests for the flow diff (T9), on real model.Graph and hand-built matches."""

from hypothesis import given, settings
from hypothesis import strategies as st

from witness.diff import flow_diff
from witness.model import Graph

IDENT = lambda g: {i: (i, "exact", 1.0) for i in range(len(g.nodes))}  # noqa: E731


def _g(nodes: list[tuple[str, str]], edges: list[tuple[int, int, str]]) -> Graph:
    """nodes: (name, role)."""
    g = Graph()
    for i, (name, role) in enumerate(nodes):
        attrs = {"name": name}
        if role:
            attrs["role"] = role
        g.add_node("CALL", ("f.py", name, "", str(i)), ("f.py", i + 1, i + 1), attrs)
    for s, d, k in edges:
        g.add_edge(s, d, k)
    return g


def _kinds(changes) -> list[str]:
    return [c.kind for c in changes]


def test_identical_graph_has_no_changes():
    g = _g([("request.coupon", "source"), ("validate_coupon", "guard"), ("db.orders.insert", "sink")],
           [(0, 1, "dflow"), (1, 2, "dflow")])
    assert flow_diff(g, g, IDENT(g)) == []


def test_guard_bypassed():
    nodes = [("request.coupon", "source"), ("validate_coupon", "guard"), ("db.orders.insert", "sink")]
    base = _g(nodes, [(0, 1, "dflow"), (1, 2, "dflow")])
    head = _g(nodes, [(0, 1, "dflow"), (0, 2, "dflow")])
    out = flow_diff(base, head, IDENT(base))
    assert _kinds(out) == ["guard_bypassed"]
    c = out[0]
    assert (c.src, c.sink, c.guard) == ("request.coupon", "db.orders.insert", "validate_coupon")
    assert c.base_path == "request.coupon -> validate_coupon -> db.orders.insert"
    assert c.head_path == "request.coupon -> db.orders.insert"


def test_guard_still_on_every_path_is_not_bypassed():
    nodes = [("s", "source"), ("g", "guard"), ("t", "sink")]
    base = _g(nodes, [(0, 1, "dflow"), (1, 2, "dflow")])
    head = _g(nodes, [(0, 1, "arg"), (1, 2, "ret")])
    assert flow_diff(base, head, IDENT(base)) == []


def test_guard_removed_node_is_bypass():
    base = _g([("s", "source"), ("g", "guard"), ("t", "sink")], [(0, 1, "dflow"), (1, 2, "dflow")])
    head = _g([("s", "source"), ("t", "sink")], [(0, 1, "dflow")])
    m = {0: (0, "exact", 1.0), 2: (1, "exact", 1.0)}
    out = flow_diff(base, head, m)
    assert _kinds(out) == ["guard_bypassed"] and out[0].guard == "g"


def test_added_and_removed_flow():
    nodes = [("s", "source"), ("t", "sink")]
    empty, flow = _g(nodes, []), _g(nodes, [(0, 1, "dflow")])
    assert _kinds(flow_diff(empty, flow, IDENT(empty))) == ["added_flow"]
    assert _kinds(flow_diff(flow, empty, IDENT(empty))) == ["removed_flow"]


def test_rerouted():
    nodes = [("s", "source"), ("a", ""), ("b", ""), ("t", "sink")]
    base = _g(nodes, [(0, 1, "dflow"), (1, 3, "dflow")])
    head = _g(nodes, [(0, 2, "dflow"), (2, 3, "dflow")])
    assert _kinds(flow_diff(base, head, IDENT(base))) == ["rerouted"]


def test_pure_rename_no_change():
    base = _g([("s", "source"), ("old", ""), ("t", "sink")], [(0, 1, "dflow"), (1, 2, "dflow")])
    head = _g([("s", "source"), ("new", ""), ("t", "sink")], [(0, 1, "dflow"), (1, 2, "dflow")])
    m = {0: (0, "exact", 1.0), 1: (1, "fingerprint", 0.85), 2: (2, "exact", 1.0)}
    assert flow_diff(base, head, m) == []


def test_depth_cap_7():
    def chain(n_edges: int) -> Graph:
        nodes = [("s", "source")] + [(f"m{i}", "") for i in range(n_edges - 1)] + [("t", "sink")]
        return _g(nodes, [(i, i + 1, "dflow") for i in range(n_edges)])

    empty7 = _g([("s", "source")] + [(f"m{i}", "") for i in range(6)] + [("t", "sink")], [])
    assert _kinds(flow_diff(empty7, chain(7), IDENT(empty7))) == ["added_flow"]
    empty8 = _g([("s", "source")] + [(f"m{i}", "") for i in range(7)] + [("t", "sink")], [])
    assert flow_diff(empty8, chain(8), IDENT(empty8)) == []


def test_path_cap_200():
    n = 300
    nodes = [("s", "source")] + [(f"m{i}", "") for i in range(n)] + [("t", "sink")]
    edges = [(0, i + 1, "dflow") for i in range(n)] + [(i + 1, n + 1, "dflow") for i in range(n)]
    head = _g(nodes, edges)
    base = _g(nodes, [])
    out = flow_diff(base, head, IDENT(base))
    assert _kinds(out) == ["added_flow"]
    assert out[0].confidence < 1.0


def test_confidence_uses_match_confidence():
    nodes = [("s", "source"), ("t", "sink")]
    base, head = _g(nodes, []), _g(nodes, [(0, 1, "dflow")])
    out = flow_diff(base, head, {0: (0, "changed_signature", 0.9), 1: (1, "exact", 1.0)})
    assert out[0].confidence == 0.9


def test_callers():
    nodes = [("checkout.total", ""), ("discount.apply", ""), ("old.caller", "")]
    base = _g(nodes, [(2, 1, "calls")])
    head = _g(nodes, [(0, 1, "calls")])
    out = flow_diff(base, head, IDENT(base))
    assert [(c.kind, c.src, c.sink) for c in out] == [
        ("new_caller", "checkout.total", "discount.apply"),
        ("lost_caller", "old.caller", "discount.apply"),
    ]


def test_unmatched_nodes_do_not_crash():
    base = _g([("s", "source"), ("g", "guard"), ("t", "sink")], [(0, 1, "dflow"), (1, 2, "dflow")])
    head = _g([("s2", "source"), ("t2", "sink"), ("n", "")], [(0, 1, "dflow"), (2, 1, "calls")])
    out = flow_diff(base, head, {})
    assert sorted(_kinds(out)) == ["added_flow", "removed_flow"]
    assert flow_diff(base, head, {99: (98, "exact", 1.0)}) is not None


def test_deterministic_order():
    nodes = [("s2", "source"), ("s1", "source"), ("t", "sink"), ("u", "sink")]
    base = _g(nodes, [])
    head = _g(nodes, [(0, 2, "dflow"), (1, 3, "dflow"), (1, 2, "dflow"), (0, 3, "dflow")])
    out = flow_diff(base, head, IDENT(base))
    assert out == flow_diff(base, head, IDENT(base))
    assert [(c.src, c.sink) for c in out] == sorted((c.src, c.sink) for c in out)


_SWAP = {"added_flow": "removed_flow", "removed_flow": "added_flow",
         "guard_bypassed": "guard_added", "guard_added": "guard_bypassed",
         "rerouted": "rerouted", "new_caller": "lost_caller", "lost_caller": "new_caller"}


@st.composite
def _graph_pair(draw):
    n = draw(st.integers(3, 7))
    roles = [draw(st.sampled_from(["", "", "source", "sink", "guard"])) for _ in range(n)]
    nodes = [(f"n{i}", roles[i]) for i in range(n)]
    pair = st.tuples(st.integers(0, n - 1), st.integers(0, n - 1),
                     st.sampled_from(["dflow", "arg", "ret", "calls"]))
    e1 = draw(st.lists(pair, max_size=12))
    e2 = draw(st.lists(pair, max_size=12))
    return _g(nodes, e1), _g(nodes, e2)


@settings(max_examples=150, deadline=None)
@given(_graph_pair())
def test_swap_symmetry(pair):
    a, b = pair
    fwd = flow_diff(a, b, IDENT(a))
    rev = flow_diff(b, a, IDENT(a))
    key = lambda cs: sorted((c.kind, c.src, c.sink, c.guard or "") for c in cs)  # noqa: E731
    assert key(rev) == key(
        [type(c)(_SWAP[c.kind], c.src, c.sink, c.guard, None, None, [], c.confidence) for c in fwd]
    )


def test_guard_bypassed_while_other_guarded_path_remains():
    nodes = [("s", "source"), ("g", "guard"), ("a", ""), ("t", "sink")]
    base = _g(nodes, [(0, 1, "dflow"), (1, 3, "dflow"), (1, 2, "dflow"), (2, 3, "dflow")])
    head = _g(nodes, [(0, 1, "dflow"), (1, 3, "dflow"), (0, 3, "dflow")])
    out = flow_diff(base, head, IDENT(base))
    assert _kinds(out) == ["guard_bypassed"]
    assert out[0].head_path == "s -> t"


def test_guard_added_when_only_some_base_paths_guarded():
    nodes = [("s", "source"), ("g", "guard"), ("t", "sink")]
    base = _g(nodes, [(0, 1, "dflow"), (1, 2, "dflow"), (0, 2, "dflow")])
    head = _g(nodes, [(0, 1, "dflow"), (1, 2, "dflow")])
    out = flow_diff(base, head, IDENT(base))
    assert _kinds(out) == ["guard_added"]
    assert out[0].base_path == "s -> t" and out[0].head_path == "s -> g -> t"


def test_kind_rank_follows_flow_kinds():
    from witness.shared import FLOW_KINDS
    nodes = [("s", "source"), ("g", "guard"), ("t", "sink"), ("s2", "source"), ("t2", "sink"),
             ("c", ""), ("d", "")]
    base = _g(nodes, [(0, 1, "dflow"), (1, 2, "dflow"), (6, 5, "calls")])
    head = _g(nodes, [(0, 2, "dflow"), (3, 4, "dflow"), (5, 6, "calls")])
    kinds = _kinds(flow_diff(base, head, IDENT(base)))
    assert kinds == ["guard_bypassed", "added_flow", "new_caller", "lost_caller"]
    assert kinds == sorted(kinds, key=FLOW_KINDS.index)
