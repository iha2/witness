"""Wave 0 placeholder tests: each produced stub fails as not implemented until its owning task lands."""

from pathlib import Path

from witness import acquire, diff, explain, match, pipeline, reduce, render, scope
from witness.model import Graph
from witness.shared import Hunk, Scope


def test_T2_add_node_returns_first_id():
    g = Graph()
    assert g.add_node("METHOD", ("a.py", "a.f", "1", ""), ("a.py", 1, 4), {}) == 0


def test_T2_has_path_returns_bool():
    assert isinstance(Graph().has_path(0, 2, {"dflow"}, set()), bool)


def test_T3_parse_hunks_reads_one_hunk():
    diff_text = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -3,1 +3,1 @@\n-a\n+b\n"
    hunks = acquire.parse_hunks(diff_text)
    assert len(hunks) == 1
    assert (hunks[0].old_path, hunks[0].old_start) == ("x.py", 3)


def test_T5_find_scope_caps_files():
    hunk = Hunk(old_path="orders/discount.py", new_path="orders/discount.py",
                old_start=2, old_len=1, new_start=2, new_len=1)
    result = scope.find_scope(Path("."), "HEAD~1", "HEAD", [hunk], 1, 2)
    assert isinstance(result, Scope)
    assert len(result.files) <= 2


def test_T8_match_returns_dict():
    assert isinstance(match.match(Graph(), Graph(), {}), dict)


def test_T9_flow_diff_returns_list():
    assert isinstance(diff.flow_diff(Graph(), Graph(), {}), list)


def test_T10_reduce_slice_returns_nodes_and_edges():
    result = reduce.reduce_slice(Graph(), [], [], 50)
    assert "nodes" in result and "edges" in result


def test_T11_validate_returns_list():
    expl = {"explanation": [{"text": "It calls `foo()`.", "cites": []}]}
    assert isinstance(explain.validate(expl, {}), list)


def test_T11_explain_returns_dict():
    assert isinstance(explain.explain({}, None), dict)


def test_T14_to_markdown_returns_str():
    assert isinstance(render.to_markdown({}), str)


def test_T15_analyze_returns_dict():
    assert isinstance(pipeline.analyze(Path("."), None, "HEAD~1", "HEAD", True, lambda event: None), dict)
