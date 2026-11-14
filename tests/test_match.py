from hypothesis import given, settings
from hypothesis import strategies as st

from witness.match import match
from witness.model import Graph


def method(g, path, q, sig="1", fp="", span=None):
    attrs = {"fingerprint": fp} if fp else {}
    return g.add_node("METHOD", (path, q, sig, ""), span or (path, 1, 4), attrs)


def test_empty_graphs():
    assert match(Graph(), Graph(), {}) == {}


def test_same_key_exact():
    a, b = Graph(), Graph()
    method(a, "a.py", "a.f")
    method(b, "a.py", "a.f")
    assert match(a, b, {}) == {0: (0, "exact", 1.0)}


def test_renamed_path_exact():
    a, b = Graph(), Graph()
    method(a, "a.py", "a.f")
    method(b, "b.py", "a.f")
    assert match(a, b, {"a.py": "b.py"}) == {0: (0, "exact", 1.0)}


def test_changed_signature():
    a, b = Graph(), Graph()
    method(a, "a.py", "a.f", "1")
    method(b, "a.py", "a.f", "2")
    assert match(a, b, {}) == {0: (0, "changed_signature", 0.9)}


def test_move_by_fingerprint():
    a, b = Graph(), Graph()
    method(a, "a.py", "a.f", fp="h1")
    method(b, "c.py", "c.g", fp="h1")
    m = match(a, b, {})
    assert m[0][0] == 0 and m[0][1] == "fingerprint"


def test_structural_same_file():
    a, b = Graph(), Graph()
    method(a, "a.py", "a.compute_total", span=("a.py", 1, 10))
    method(b, "a.py", "a.compute_totals", sig="x", span=("a.py", 1, 11))
    # same qname family, different sig -> tier 2 misses (qname differs), tier 4 hits
    m = match(a, b, {})
    assert m[0][1] == "structural"


def test_no_match_across_unrelated():
    a, b = Graph(), Graph()
    method(a, "a.py", "a.f")
    method(b, "z.py", "z.q", sig="9")
    assert match(a, b, {}) == {}


def test_sub_method_ordinal():
    a, b = Graph(), Graph()
    ma = method(a, "a.py", "a.f", "1", span=("a.py", 1, 10))
    mb = method(b, "a.py", "a.f", "2", span=("a.py", 1, 10))
    ca = a.add_node("CALL", ("a.py", "a.f", "1", "c0"), ("a.py", 2, 2), {"name": "g"})
    cb = b.add_node("CALL", ("a.py", "a.f", "2", "c0"), ("a.py", 2, 2), {"name": "g"})
    m = match(a, b, {})
    assert m[ma] == (mb, "changed_signature", 0.9)
    assert m[ca] == (cb, "ordinal", 0.8)


def test_no_double_assign():
    a, b = Graph(), Graph()
    method(a, "a.py", "a.f", fp="h")
    method(a, "a.py", "a.g", fp="h")
    method(b, "c.py", "c.f", fp="h")
    m = match(a, b, {})
    heads = [v[0] for v in m.values()]
    assert len(heads) == len(set(heads)) == 1


def test_duplicate_keys_paired_in_order():
    a, b = Graph(), Graph()
    for g in (a, b):
        g.add_node("CALL", ("a.py", "f", "1", "x"), None, {})
        g.add_node("CALL", ("a.py", "f", "1", "x"), None, {})
    assert match(a, b, {}) == {0: (0, "exact", 1.0), 1: (1, "exact", 1.0)}


node_st = st.tuples(
    st.sampled_from(["METHOD", "CALL", "PARAM"]),
    st.sampled_from(["a.py", "b.py"]),
    st.sampled_from(["f", "g", "h"]),
    st.sampled_from(["1", "2"]),
    st.sampled_from(["", "x", "y"]),
    st.sampled_from(["", "fp1", "fp2"]),
)


@settings(max_examples=60, deadline=None)
@given(st.lists(node_st, max_size=12))
def test_identity_property(nodes):
    g = Graph()
    for kind, p, q, s, x, fp in nodes:
        g.add_node(kind, (p, q, s, x), (p, 1, 5), {"fingerprint": fp} if fp else {})
    m = match(g, g, {})
    assert m == {i: (i, "exact", 1.0) for i in range(len(nodes))}
