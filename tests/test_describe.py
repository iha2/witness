"""Tests for the description check (T12). explain.validate is replaced by a fake."""

import json

from witness import describe
from witness.shared import FlowChange, Hunk


def _change(kind: str = "guard_bypassed", src: str = "a", sink: str = "b") -> FlowChange:
    return FlowChange(kind, src, sink, None, None, None, ["h1"], 0.9)


def _hunk() -> Hunk:
    return Hunk("h1", "x.py", "x.py", 1, 1, 1, 1, "x")


def _ok(expl: dict, pack: dict) -> list[str]:
    return []


def test_no_llm_returns_empty_lists_with_reason():
    out = describe.check("t", "body", [_change()], [_hunk()], None, validate=_ok)
    assert out["described_not_found"] == []
    assert out["found_not_described"] == []
    assert out["reason"]


def test_empty_body():
    called = []
    out = describe.check("", "  ", [_change()], [_hunk()], lambda p: called.append(p) or "", validate=_ok)
    assert out["described_not_found"] == [] and out["found_not_described"] == []
    assert out["reason"] and not called


def test_claim_not_found_and_change_not_described():
    c = _change()
    cid = describe.change_id(c)
    other = _change("added_flow", "p", "q")

    def llm(prompt: str) -> str:
        assert cid in prompt
        return json.dumps({"claims": [{"text": "adds rate limiting", "matches": []},
                                      {"text": "skips validation", "matches": [cid]}]})

    out = describe.check("t", "b", [c, other], [_hunk()], llm, validate=_ok)
    assert out["described_not_found"] == ["adds rate limiting"]
    assert out["found_not_described"] == [describe.change_id(other)]
    assert "reason" not in out


def test_unknown_id_counts_as_not_found():
    llm = lambda p: json.dumps({"claims": [{"text": "x", "matches": ["deadbeef00"]}]})  # noqa: E731
    out = describe.check("t", "b", [_change()], [_hunk()], llm, validate=_ok)
    assert out["described_not_found"] == ["x"]


def test_failed_validation_drops_match():
    c = _change()
    llm = lambda p: json.dumps({"claims": [{"text": "x", "matches": [describe.change_id(c)]}]})  # noqa: E731
    out = describe.check("t", "b", [c], [_hunk()], llm, validate=lambda e, p: ["no-cite"])
    assert out["described_not_found"] == ["x"]
    assert out["found_not_described"] == [describe.change_id(c)]


def test_bad_json_and_llm_error_degrade():
    out = describe.check("t", "b", [_change()], [_hunk()], lambda p: "nope", validate=_ok)
    assert out["found_not_described"] == [] and out["reason"]

    def boom(p: str) -> str:
        raise RuntimeError("down")

    out = describe.check("t", "b", [_change()], [_hunk()], boom, validate=_ok)
    assert out["found_not_described"] == [] and out["reason"]


def test_pack_matches_explain_build_pack_shape():
    """With the real explain.validate, a grounded claim citing a change is matched (no KeyError)."""
    c = _change("guard_bypassed", "request.coupon", "db.insert")
    cid = describe.change_id(c)
    llm = lambda p: json.dumps({"claims": [  # noqa: E731
        {"text": "It bypasses the check on `request.coupon`.", "matches": [cid]},
        {"text": "It now calls `request.coupon`.", "matches": [cid]},
    ]})
    out = describe.check("t", "b", [c], [_hunk()], llm)
    assert out["described_not_found"] == ["It now calls `request.coupon`."]
    assert out["found_not_described"] == []


def test_json_wrapped_in_prose():
    llm = lambda p: 'Sure:\n{"claims": []}\nDone'  # noqa: E731
    c = _change()
    out = describe.check("t", "b", [c], [_hunk()], llm, validate=_ok)
    assert out["found_not_described"] == [describe.change_id(c)]
