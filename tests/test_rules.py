"""Tests for check and sink rules (T7). Uses a minimal fake graph (model.Graph is T2)."""

from pathlib import Path

import pytest

from witness import rules
from witness.shared import UsageError


class _Node:
    def __init__(self, kind: str, attrs: dict[str, str]):
        self.kind = kind
        self.attrs = attrs


class FakeGraph:
    def __init__(self) -> None:
        self.nodes: list[_Node] = []

    def add(self, kind: str, name: str) -> _Node:
        n = _Node(kind, {"name": name})
        self.nodes.append(n)
        return n


def test_sink_in_python():
    g = FakeGraph()
    n = g.add("CALL", "db.orders.insert")
    rules.tag(g, "python", None)
    assert n.attrs["role"] == "sink"


def test_source_and_untouched():
    g = FakeGraph()
    src = g.add("CALL", "request.args.get")
    plain = g.add("CALL", "compute_total")
    rules.tag(g, "python", None)
    assert src.attrs["role"] == "source"
    assert "role" not in plain.attrs


def test_repo_rules_override(tmp_path: Path):
    extra = tmp_path / "rules.yaml"
    extra.write_text("guard:\n  - 'ensure_*'\n")
    g = FakeGraph()
    n = g.add("CALL", "ensure_coupon")
    rules.tag(g, "python", extra)
    assert n.attrs["role"] == "guard"


def test_repo_rule_beats_pack(tmp_path: Path):
    extra = tmp_path / "rules.yaml"
    extra.write_text("guard:\n  - 'db.orders.insert'\n")
    g = FakeGraph()
    n = g.add("CALL", "db.orders.insert")
    rules.tag(g, "python", extra)
    assert n.attrs["role"] == "guard"


def test_guard_pattern_validate():
    g = FakeGraph()
    n = g.add("CALL", "validate_coupon")
    rules.tag(g, "python", None)
    assert n.attrs["role"] == "guard"


def test_bad_yaml(tmp_path: Path):
    extra = tmp_path / "broken.yaml"
    extra.write_text("guard: [unclosed\n")
    with pytest.raises(UsageError, match="broken.yaml"):
        rules.tag(FakeGraph(), "python", extra)


def test_bad_role_names_file(tmp_path: Path):
    extra = tmp_path / "odd.yaml"
    extra.write_text("sinks: [x]\n")
    with pytest.raises(UsageError, match="odd.yaml"):
        rules.tag(FakeGraph(), "python", extra)


def test_missing_extra_is_ignored(tmp_path: Path):
    g = FakeGraph()
    assert rules.tag(g, "python", tmp_path / "none.yaml") is g


def test_unknown_language_uses_common_pack():
    g = FakeGraph()
    n = g.add("CALL", "validate_x")
    rules.tag(g, "cobol", None)
    assert n.attrs["role"] == "guard"


@pytest.mark.parametrize("lang", ["python", "java", "javascript", "c", "go"])
def test_shipped_packs_load(lang: str):
    path = Path(rules.__file__).parent / "rules" / f"{lang}.yaml"
    assert rules.load_rule_file(path)
