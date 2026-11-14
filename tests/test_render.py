"""T14 renderer tests. The explain.explain seam is exercised through a hand-built report."""

import copy
import json
import re
from pathlib import Path

import pytest

from witness import render
from witness.shared import WitnessError

SCHEMA = Path(__file__).parents[1] / "schema" / "witness.report.v1.json"

GRAPH = {
    "root": "hunk 7f00e21b9c",
    "before": {
        "nodes": [
            {"id": "a", "label": "request.coupon", "shape": "source"},
            {"id": "v", "label": "validate_coupon", "shape": "node"},
            {"id": "d", "label": "charge(amount)", "shape": "sink"},
        ],
        "edges": [{"src": "a", "dst": "v"}, {"src": "v", "dst": "d", "label": "a|b"}],
    },
    "after": {
        "nodes": [
            {"id": "a", "label": "request.coupon", "shape": "source"},
            {"id": "d", "label": 'charge("amount")', "shape": "sink"},
        ],
        "edges": [{"src": "a", "dst": "d", "status": "added"}],
    },
}


@pytest.fixture
def report() -> dict:
    return {
        "meta": {"schema": "witness/v1", "repo": "acme/shop", "pr": 482,
                 "title": "Simplify discount rules", "base": "3f2a1c9", "head": "9b7e044",
                 "engine": "joern", "language": "python", "files_in_scope": 214,
                 "model": "claude-sonnet-5-5"},
        "coverage": {"unanalysed": 3, "grounded": 2, "total": 2},
        "overview": {
            "look_first": [{"kind": "guard_bypassed", "text": "`a|b` no longer validated",
                            "hunk": "7f00e21b9c"}],
            "graph": GRAPH,
        },
        "description_check": {"described_not_found": ["adds rate limiting"],
                              "found_not_described": [{"text": "validation removed",
                                                       "hunk": "7f00e21b9c"}]},
        "hunks": [
            {"id": "7f00e21b9c", "path": "orders/coupon.py", "start": 12, "end": 19,
             "title": "Coupon codes are no longer validated", "kinds": ["guard_bypassed"],
             "diff": "-    validate_coupon(code)\n+    Coupon(code)\n", "templated": False,
             "explanation": [{"text": "`apply_coupon()` skips `validate_coupon()`.",
                              "cites": ["F4"]}],
             "graph": GRAPH},
            {"id": "1122334455", "path": "orders/coupon.py", "start": 40, "end": 41,
             "title": "log text", "kinds": [], "templated": True, "explanation": []},
        ],
        "flow_changes": [
            {"kind": "guard_bypassed", "src": "request.coupon", "sink": "db.orders.insert",
             "guard": "validate_coupon", "hunks": ["7f00e21b9c"], "confidence": 0.9,
             "path": "orders/coupon.py", "line": 12,
             "head_steps": [{"path": "api/orders.py", "line": 22, "text": "coupon = req"},
                            {"path": "orders/repo.py", "line": 58, "text": "db.orders.insert"}]},
            {"kind": "added_flow", "src": "a", "sink": "b", "guard": None,
             "hunks": ["1122334455"], "path": "orders/coupon.py", "line": 40},
        ],
        "evidence": [{"id": "F4", "text": "call edge missing in head"}],
    }


def blocks(md: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", md, re.S)


def test_markdown_sections(report):
    md = render.to_markdown(report)
    assert md.startswith("# Witness report ·")
    order = [md.index(f"## {s}") for s in
             ["Look here first", "How the data flow changes", "Hunks", "Evidence", "Coverage"]]
    assert order == sorted(order)
    assert "## Description check" in md


def test_mermaid_side_by_side(report):
    bl = blocks(render.to_markdown(report))
    assert len(bl) == 2
    for b in bl:
        assert b.startswith("flowchart TD\n")
        assert len(re.findall(r"^\s+R\(\[", b, re.M)) == 1
        assert re.search(r'--- B\["before"\]', b) and re.search(r'R --- A\["after"\]', b)
        assert not re.search(r"^\s+(?!R\b)\w+\(\[.*\]\)\s*$", b.split("\n", 2)[1], re.M)
        for banned in ("subgraph", "style ", "classDef"):
            assert banned not in b


def test_mermaid_quotes_labels(report):
    b = blocks(render.to_markdown(report))[0]
    assert '[("charge(amount)")]' in b
    assert "charge(amount)" not in b.replace('"charge(amount)"', "")
    assert 'charge(#quot;amount#quot;)' in b
    assert '-->|"a#124;b"|' in b  # pipe in an edge label is entity-escaped
    assert "==>" in b


def test_markdown_escapes_pipes(report):
    md = render.to_markdown(report)
    row = next(ln for ln in md.splitlines() if "no longer validated" in ln and ln.startswith("|"))
    assert "`a\\|b`" in row
    assert len(re.findall(r"(?<!\\)\|", row)) == 5  # 4 columns


def test_text_has_markers(report):
    t = render.to_text(report)
    assert "1." in t and "+" in t and "7f00e21b9c" in t
    assert "\x1b" not in t


def test_sarif_codeflows(report):
    s = render.to_sarif(report)
    assert s["version"] == "2.1.0"
    res = s["runs"][0]["results"]
    assert [r["ruleId"] for r in res] == ["guard_bypassed", "added_flow"]
    assert res[0]["level"] == "error"
    locs = res[0]["codeFlows"][0]["threadFlows"][0]["locations"]
    assert [x["location"]["physicalLocation"]["region"]["startLine"] for x in locs] == [22, 58]
    assert res[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == \
        "orders/coupon.py"
    assert "codeFlows" not in res[1]
    json.dumps(s)


def test_annotations_jsonl(report):
    lines = render.to_annotations(report).splitlines()
    rows = [json.loads(x) for x in lines]
    assert [r["hunk_id"] for r in rows] == ["7f00e21b9c", "1122334455"]
    assert rows[0]["path"] == "orders/coupon.py" and rows[0]["start"] == 12
    assert "skips" in rows[0]["body"]


def test_validate_report_ok_and_bad(report):
    render.validate_report(report)
    bad = copy.deepcopy(report)
    del bad["hunks"][0]["id"]
    with pytest.raises(WitnessError):
        render.validate_report(bad)
    bad = copy.deepcopy(report)
    bad["hunks"][0]["explanation"][0]["cites"] = []
    with pytest.raises(WitnessError):
        render.validate_report(bad)
    bad = copy.deepcopy(report)
    bad["flow_changes"][0]["kind"] = "nope"
    with pytest.raises(WitnessError):
        render.validate_report(bad)


def test_schema_file_agrees(report):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text())
    jsonschema.validate(report, schema)
    bad = copy.deepcopy(report)
    bad["flow_changes"][0]["kind"] = "nope"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_no_credentials_in_report_output(report):
    report["meta"]["title"] = "t"
    for out in (render.to_markdown(report), render.to_text(report),
                render.to_annotations(report), json.dumps(render.to_sarif(report))):
        assert "x-access-token" not in out
