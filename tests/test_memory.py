import json
import os

from witness import memory


def test_compare_example():
    result = memory.compare(["a", "b"], {"b": ("s", "k"), "c": ("s", "k")})
    assert result == {"new": ["c"], "resolved": ["a"], "seen": ["b"]}


def test_load_missing_returns_empty(tmp_path):
    assert memory.load(tmp_path / "nope.json") == []


def test_save_atomic(tmp_path, monkeypatch):
    target = tmp_path / "reviews" / "482.json"
    calls = []
    real_replace = os.replace

    def recording_replace(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(memory.os, "replace", recording_replace)

    memory.save(target, "abc123", ["x", "y"])

    assert len(calls) == 1
    src, dst = calls[0]
    assert dst == str(target)
    assert src != dst
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "head": "abc123",
        "ids": ["x", "y"],
    }
    assert [p.name for p in target.parent.iterdir()] == ["482.json"]


def test_save_then_load_roundtrip(tmp_path):
    target = tmp_path / "482.json"
    memory.save(target, "deadbeef", ["f1", "f2"])
    assert memory.load(target) == ["f1", "f2"]
