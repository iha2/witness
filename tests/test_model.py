import pytest

from witness.model import Graph, load_graph, save_graph

K = ("a.py", "a.f", "1", "")


def test_by_key_lookup():
    g = Graph()
    assert g.add_node("METHOD", K, ("a.py", 1, 4), {}) == 0
    assert g.by_key(K) == 0
    assert g.by_key(("x", "y", "z", "")) is None


def test_chain_and_without():
    g = Graph()
    for i in range(3):
        g.add_node("X", ("f", "n", str(i), ""), None, {})
    g.add_edge(0, 1, "dflow")
    g.add_edge(1, 2, "dflow")
    assert g.has_path(0, 2, {"dflow"}, set())
    assert not g.has_path(0, 2, {"dflow"}, {1})
    assert not g.has_path(0, 2, {"call"}, set())


def test_cycle_has_path():
    g = Graph()
    for i in range(3):
        g.add_node("X", ("f", "n", str(i), ""), None, {})
    g.add_edge(0, 1, "dflow")
    g.add_edge(1, 0, "dflow")
    assert g.has_path(0, 1, {"dflow"}, set())
    assert not g.has_path(0, 2, {"dflow"}, set())


def test_unknown_node_raises():
    g = Graph()
    g.add_node("X", K, None, {})
    with pytest.raises(KeyError):
        g.add_edge(0, 99, "dflow")


def test_roundtrip_sqlite(tmp_path):
    g = Graph()
    g.add_node("METHOD", K, ("a.py", 1, 4), {"name": "f"})
    g.add_node("CALL", ("a.py", "a.f", "2", "g"), None, {})
    g.add_edge(0, 1, "call")
    g.add_edge(1, 0, "dflow")
    p = tmp_path / "g.db"
    save_graph(g, p)
    h = load_graph(p)
    assert h.nodes == g.nodes
    assert h.edges == g.edges
    assert h.by_key(K) == 0


def test_has_path_kind_filter_mixed_and_without_endpoints():
    g = Graph()
    for i in range(3):
        g.add_node("X", ("f", "n", str(i), ""), None, {})
    g.add_edge(0, 1, "dflow")
    g.add_edge(1, 2, "call")
    assert not g.has_path(0, 2, {"dflow"}, set())
    assert g.has_path(0, 2, {"dflow", "call"}, set())
    assert not g.has_path(0, 2, {"dflow", "call"}, {2})
    assert not g.has_path(0, 2, {"dflow", "call"}, {0})


def test_roundtrip_wal_none_span_parallel_edges(tmp_path):
    import sqlite3

    g = Graph()
    g.add_node("A", ("p", "q", "s", ""), None, {})
    g.add_node("B", ("p", "q2", "s", "x"), ("p", 3, 9), {"k": "v"})
    g.add_edge(0, 1, "call")
    g.add_edge(0, 1, "dflow")
    g.add_edge(0, 1, "call")  # duplicate ignored
    p = tmp_path / "g.db"
    save_graph(g, p)
    save_graph(g, p)  # overwrite is safe
    h = load_graph(p)
    assert h.nodes == g.nodes
    assert h.edges == g.edges == [(0, 1, "call"), (0, 1, "dflow")]
    con = sqlite3.connect(p)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        con.close()
