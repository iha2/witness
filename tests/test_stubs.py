"""Wave 0 placeholder tests: each produced stub fails as not implemented until its owning task lands."""

from pathlib import Path

from witness import acquire, explain, match, render, scope
from witness.model import Graph
from witness.shared import Hunk, Scope


def _hunk() -> Hunk:
    return Hunk(id="0000000000", old_path="a.py", new_path="a.py",
                old_start=1, old_len=1, new_start=1, new_len=1, text="-a\n+b\n")


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
    hunk = Hunk(id="0000000000", old_path="orders/discount.py", new_path="orders/discount.py",
                old_start=2, old_len=1, new_start=2, new_len=1, text="-a\n+b\n")
    result = scope.find_scope(Path("."), "HEAD~1", "HEAD", [hunk], 1, 2)
    assert isinstance(result, Scope)
    assert len(result.files) <= 2


def test_T8_match_returns_dict():
    assert isinstance(match.match(Graph(), Graph(), {}), dict)


def test_T11_validate_returns_list():
    pack = explain.build_pack(_hunk(), [], {"nodes": []})
    expl = {"explanation": [{"text": "It calls `foo()`.", "cites": []}]}
    assert isinstance(explain.validate(expl, pack), list)


def test_T11_explain_returns_dict():
    pack = explain.build_pack(_hunk(), [], {"nodes": []})
    assert isinstance(explain.explain(pack, None), dict)


def test_T14_to_markdown_returns_str():
    report = {
        "meta": {"schema": "witness/v1", "title": "t", "base": "a", "head": "b"},
        "coverage": {}, "overview": {"look_first": []}, "hunks": [], "flow_changes": [],
        "evidence": [],
    }
    render.validate_report(report)
    assert isinstance(render.to_markdown(report), str)
