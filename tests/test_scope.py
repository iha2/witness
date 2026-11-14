"""Tests for the scope finder (T5)."""

import subprocess
from pathlib import Path

import pytest

from witness import scope
from witness.shared import Hunk, hunk_id


def _hunk(old: str, new: str, start: int = 1) -> Hunk:
    return Hunk(hunk_id(new, start, start, "x"), old, new, start, 1, start, 1, "x")


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _commit(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    return tmp_path


def test_changed_names_function_and_module(tmp_path: Path):
    f = tmp_path / "orders" / "discount.py"
    f.parent.mkdir()
    f.write_text("import os\n\n\ndef apply(cart):\n    x = 1\n    return x\n")
    h = _hunk("orders/discount.py", "orders/discount.py", start=5)
    assert scope.changed_names(tmp_path, [h]) == ["apply", "orders.discount"]


def test_changed_names_outside_function_is_module_only(tmp_path: Path):
    (tmp_path / "a.py").write_text("def f():\n    pass\n\nX = 1\n")
    h = _hunk("a.py", "a.py", start=4)
    assert scope.changed_names(tmp_path, [h]) == ["a"]


def test_cap_keeps_changed_files(repo: Path):
    (repo / "core.py").write_text("def helper():\n    return 1\n")
    for n in ("u1.py", "u2.py", "u3.py"):
        (repo / n).write_text("from core import helper\n")
    base = _commit(repo, "base")
    (repo / "core.py").write_text("def helper():\n    return 2\n")
    head = _commit(repo, "head")
    s = scope.find_scope(repo, base, head, [_hunk("core.py", "core.py")], 1, 2)
    assert s.files[0] == "core.py"
    assert len(s.files) == 2
    assert len(s.unanalysed) == 2
    assert set(s.files) | set(s.unanalysed) == {"core.py", "u1.py", "u2.py", "u3.py"}


def test_cap_smaller_than_changed_keeps_all_changed(repo: Path):
    names = ("a.py", "b.py", "c.py")
    for n in names:
        (repo / n).write_text("def f():\n    return 1\n")
    base = _commit(repo, "base")
    for n in names:
        (repo / n).write_text("def f():\n    return 2\n")
    head = _commit(repo, "head")
    s = scope.find_scope(repo, base, head, [_hunk(n, n) for n in names], 1, 1)
    assert s.files == list(names)
    assert s.unanalysed == []


def test_union_base_head(repo: Path):
    (repo / "gone.py").write_text("def gone():\n    return 1\n")
    (repo / "keep.py").write_text("def keep():\n    return 1\n")
    base = _commit(repo, "base")
    _git(repo, "rm", "-q", "gone.py")
    (repo / "keep.py").write_text("def keep():\n    return 2\n")
    head = _commit(repo, "head")
    hunks = [_hunk("gone.py", "/dev/null"), _hunk("keep.py", "keep.py")]
    s = scope.find_scope(repo, base, head, hunks, 1, 10)
    assert "gone.py" in s.files
    assert "keep.py" in s.files


def test_caller_only_in_base_is_found(repo: Path):
    (repo / "core.py").write_text("def helper():\n    return 1\n")
    (repo / "old_caller.py").write_text("helper()\n")
    base = _commit(repo, "base")
    _git(repo, "rm", "-q", "old_caller.py")
    (repo / "core.py").write_text("def helper():\n    return 2\n")
    head = _commit(repo, "head")
    s = scope.find_scope(repo, base, head, [_hunk("core.py", "core.py")], 1, 10)
    assert "old_caller.py" in s.files


def test_grep_special_chars(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(scope.subprocess, "run", fake_run)
    scope._grep_files(tmp_path, "HEAD", "a.b$c")
    argv = calls[0]
    assert argv.index("-F") < argv.index("-e")
    assert argv[argv.index("-e") + 1] == "a.b$c"


def test_hops_zero_only_changed(repo: Path):
    (repo / "core.py").write_text("def helper():\n    return 1\n")
    (repo / "u.py").write_text("helper()\n")
    base = _commit(repo, "base")
    (repo / "core.py").write_text("def helper():\n    return 2\n")
    head = _commit(repo, "head")
    s = scope.find_scope(repo, base, head, [_hunk("core.py", "core.py")], 0, 10)
    assert s.files == ["core.py"]
