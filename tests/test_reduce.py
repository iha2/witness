from witness.model import Graph
from witness.reduce import reduce_slice
from witness.shared import FlowChange


def chain(n):
    g = Graph()
    for i in range(n):
        g.add_node("METHOD", ("a.py", f"f{i}", "1", ""), ("a.py", i, i), {"name": f"f{i}"})
    for i in range(n - 1):
        g.add_edge(i, i + 1, "dflow")
    return g


def fc(kind, src, sink, guard=None):
    return FlowChange(kind, src, sink, guard, None, None, [], 1.0)


def test_budget_truncates_and_reports():
    g = Graph()
    g.add_node("METHOD", ("a.py", "hub", "1", ""), ("a.py", 1, 1), {"name": "hub"})
    for i in range(79):
        n = g.add_node("METHOD", ("a.py", f"c{i}", "1", ""), ("a.py", 2, 2), {"name": f"c{i}"})
        g.add_edge(n, 0, "calls")
    r = reduce_slice(g, [0], [], 50)
    assert len(r["nodes"]) == 50
    assert r["truncated"] is True and r["dropped"] == 30
    assert r["nodes"][0]["role"] == "enclosing"
    assert r["nodes"][1]["role"] == "caller"


def test_truncation_always_reported():
    g = chain(3)
    r = reduce_slice(g, [0], [], 50)
    assert r["truncated"] is False and r["dropped"] == 0
    assert {"nodes", "edges", "truncated", "dropped"} <= set(r)
    r2 = reduce_slice(g, [0], [], 1)
    assert r2["truncated"] is True and r2["dropped"] == 2


def test_rank_order():
    g = Graph()
    g.add_node("METHOD", ("a.py", "seed", "1", ""), ("a.py", 1, 1), {"name": "seed"})
    for name in ("late", "first", "mid"):
        n = g.add_node("METHOD", ("a.py", name, "1", ""), ("a.py", 2, 2), {"name": name})
        g.add_edge(0, n, "dflow")
    changes = [fc("new_caller", "late", "x"), fc("guard_bypassed", "first", "y", "v"),
               fc("added_flow", "mid", "z")]
    r = reduce_slice(g, [0], changes, 50)
    assert [n["name"] for n in r["nodes"]] == ["seed", "first", "mid", "late"]


def test_flows_not_touching_changes_are_filtered():
    g = Graph()
    for nm in ("seed", "hit", "miss"):
        g.add_node("METHOD", ("a.py", nm, "1", ""), ("a.py", 1, 1), {"name": nm})
    g.add_edge(0, 1, "dflow")
    g.add_edge(0, 2, "dflow")
    r = reduce_slice(g, [0], [fc("added_flow", "seed", "hit")], 50)
    assert {n["name"] for n in r["nodes"]} == {"seed", "hit"}


def test_overflow_rolled_up_by_file():
    g = Graph()
    g.add_node("METHOD", ("a.py", "hub", "1", ""), ("a.py", 1, 1), {"name": "hub"})
    for i in range(6):
        f = "b.py" if i < 4 else "c.py"
        n = g.add_node("METHOD", (f, f"c{i}", "1", ""), (f, 2, 2), {"name": f"c{i}"})
        g.add_edge(n, 0, "calls")
    r = reduce_slice(g, [0], [], 3)
    assert r["dropped"] == 4 and sum(r["rolled_up"].values()) == 4


def test_depth_cap():
    g = chain(12)
    r = reduce_slice(g, [0], [], 50)
    assert len(r["nodes"]) == 8  # seed + 7 hops
