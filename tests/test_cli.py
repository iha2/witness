import json
import subprocess
from pathlib import Path

import pytest

from witness import cli, doctor, pipeline
from witness.model import Graph
from witness.shared import EnvError


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.py").write_text("def f(x):\n    return x\n")
    git(r, "add", ".")
    git(r, "commit", "-qm", "c1")
    (r / "a.py").write_text("def f(x):\n    return x + 1\n")
    git(r, "commit", "-qam", "c2")
    return r


def fakes(version="1"):
    def build(checkout, files):
        g = Graph()
        g.add_node("METHOD", ("a.py", "a.f", "1", ""), ("a.py", 1, 2), {})
        return g, version

    return {"build": build, "flow_diff": lambda b, h, m: [], "reduce": lambda *a: {},
            "checkout": lambda sha: Path(".")}


def test_events_order(repo):
    events = []
    rep = pipeline.analyze(repo, None, "HEAD~1", "HEAD", True, events.append, fakes())
    kinds = [e["type"] for e in events]
    assert kinds.index("hunks") < kinds.index("deep_ready")
    assert rep["schema"] == "witness.report.v1"
    assert rep["hunks"] and rep["coverage"]["partial"] is False


def test_version_mismatch_is_env_error(repo):
    calls = iter(["1", "2"])

    def build(checkout, files):
        return Graph(), next(calls)

    st = fakes()
    st["build"] = build
    with pytest.raises(EnvError):
        pipeline.analyze(repo, None, "HEAD~1", "HEAD", True, lambda e: None, st)


def test_no_java_lists_hunks_exit_4(repo, monkeypatch, capsys):
    monkeypatch.setattr(pipeline.shutil, "which", lambda name: None)
    code = cli.main(["analyze", "--repo", str(repo), "--base", "HEAD~1", "--head", "HEAD", "--no-llm"])
    out = capsys.readouterr().out
    assert code == 4
    assert "a.py" in out and "run witness doctor" in out


def test_json_format_valid(repo, monkeypatch, capsys):
    monkeypatch.setattr(pipeline.shutil, "which", lambda name: None)
    code = cli.main(["analyze", "--repo", str(repo), "--base", "HEAD~1", "--head", "HEAD",
                     "--no-llm", "--format", "json"])
    assert code == 4
    assert json.loads(capsys.readouterr().out)["schema"] == "witness.report.v1"


def test_via_hunks_filled(repo):
    from witness.shared import FlowChange

    def build(checkout, files):
        g = Graph()
        g.add_node("METHOD", ("a.py", "a.f", "1", ""), ("a.py", 1, 2), {})
        g.add_node("CALL", ("a.py", "a.f", "1", "c"), ("a.py", 2, 2), {"name": "sink_fn"})
        return g, "1"

    st = fakes()
    st["build"] = build
    st["flow_diff"] = lambda b, h, m: [
        FlowChange("added_flow", "src", "sink_fn", None, None, "src -> sink_fn", [], 1.0)
    ]
    rep = pipeline.analyze(repo, None, "HEAD~1", "HEAD", True, lambda e: None, st)
    assert rep["flow_changes"][0]["hunks"] == [rep["hunks"][0]["id"]]
    assert rep["changes"][0]["via_hunks"] == [rep["hunks"][0]["id"]]


def test_bad_flag_exit_2(capsys):
    assert cli.main(["analyze", "--bogus"]) == 2
    assert cli.main(["analyze"]) == 2
    assert cli.main([]) == 2


def test_doctor_install_needs_yes(monkeypatch):
    ran = []
    msg = doctor.install(False, runner=lambda d: ran.append(d))
    assert ran == [] and "--yes" in msg
    doctor.install(True, runner=lambda d: ran.append(d))
    assert len(ran) == 1


def test_main_defaults_to_sys_argv(monkeypatch):
    monkeypatch.setattr("sys.argv", ["witness", "analyze", "--bogus"])
    assert cli.main() == 2


def test_via_hunks_with_real_flow_diff(repo):
    """Real diff.flow_diff output (via_hunks=[]) gets attributed to the hunk touching the sink."""
    def mk(with_edge):
        g = Graph()
        g.add_node("METHOD", ("a.py", "a.f", "1", ""), ("a.py", 1, 2), {"name": "f"})
        g.add_node("CALL", ("a.py", "src", "1", "s"), ("a.py", 1, 1), {"name": "req.src", "role": "source"})
        g.add_node("CALL", ("a.py", "sink", "1", "t"), ("a.py", 2, 2), {"name": "db.sink", "role": "sink"})
        if with_edge:
            g.add_edge(1, 2, "dflow")
        return g

    graphs = iter([mk(False), mk(True)])
    st = fakes()
    st["build"] = lambda checkout, files: (next(graphs), "1")
    del st["flow_diff"]
    rep = pipeline.analyze(repo, None, "HEAD~1", "HEAD", True, lambda e: None, st)
    added = [c for c in rep["changes"] if c["kind"] == "added_flow"]
    assert added
    hid = rep["hunks"][0]["id"]
    assert all(c["via_hunks"] == [hid] for c in added)


def test_seed_map_resolves_base_ids_through_match():
    from witness.shared import Hunk, hunk_id

    bg, hg = Graph(), Graph()
    bg.add_node("METHOD", ("a.py", "old", "1", ""), ("a.py", 1, 5), {})
    hg.add_node("METHOD", ("a.py", "pad", "1", ""), ("a.py", 100, 101), {})
    hg.add_node("METHOD", ("a.py", "old", "1", ""), ("a.py", 1, 5), {})
    h = Hunk(hunk_id("a.py", 2, 2, "x"), "a.py", "a.py", 2, 1, 2, 0, "x")
    seeds = pipeline._seed_map([h], bg, hg, {0: (1, "exact", 1.0)}, {})
    assert seeds[h.id] == [1]  # base id 0 is translated to head id 1, never used raw


def test_errors_redact_credentials(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret123")

    def boom(*a, **k):
        raise EnvError("fetch https://user:pw@host/x failed with ghp_secret123")

    monkeypatch.setattr(pipeline, "analyze", boom)
    assert cli.main(["analyze", "--base", "a", "--head", "b"]) == 3
    err = capsys.readouterr().err
    assert "ghp_secret123" not in err and "pw@" not in err


def test_doctor_download_path(monkeypatch, tmp_path):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"#!/bin/sh\n"

    monkeypatch.setattr(doctor.urllib.request, "urlopen",
                        lambda url, timeout=None: seen.update(url=url, timeout=timeout) or Resp())
    ran = []
    monkeypatch.setattr(doctor.subprocess, "run", lambda argv, check: ran.append(argv))
    doctor._download_and_run(tmp_path / "j")
    assert seen["url"] == doctor.INSTALL_URL and seen["timeout"]
    assert ran[0][0] == "bash" and any(a.startswith("--install-dir=") for a in ran[0])


def test_pipeline_smoke_end_to_end(tmp_path):
    from witness import render

    r = tmp_path / "smoke"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.py").write_text("def f(c):\n    ok = zzcheck(c)\n    zzstore(c)\n")
    git(r, "add", ".")
    git(r, "commit", "-qm", "c1")
    (r / "a.py").write_text("def f(c):\n    ok = c\n    zzstore(c)\n")
    git(r, "commit", "-qam", "c2")

    def graph(guarded):
        g = Graph()
        g.add_node("METHOD", ("a.py", "a.f", "1", ""), ("a.py", 1, 3), {"name": "a.f"})
        for i, (name, role) in enumerate([("zzsrc", "source"), ("zzcheck", "guard"), ("zzstore", "sink")]):
            line = 1 + i
            g.add_node("CALL", ("a.py", name, "", str(line)), ("a.py", line, line),
                       {"name": name, "role": role})
        for s, d in ([(1, 2), (2, 3)] if guarded else [(1, 2), (1, 3)]):
            g.add_edge(s, d, "dflow")
        return g

    base_sha, head_sha = git(r, "rev-parse", "HEAD~1"), git(r, "rev-parse", "HEAD")
    graphs = {base_sha: graph(True), head_sha: graph(False)}
    stages = {"checkout": lambda sha: sha, "build": lambda sha, files: (graphs[sha], "1")}
    rep = pipeline.analyze(r, None, "HEAD~1", "HEAD", True, lambda e: None, stages)

    assert rep["schema"] == "witness.report.v1"
    assert rep["coverage"]["partial"] is False
    assert rep["changes"]
    hunk_ids = {h["id"] for h in rep["hunks"]}
    assert hunk_ids and set(rep["slices"]) == hunk_ids
    assert all("explanation" in h for h in rep["hunks"])
    render.validate_report(rep)
    bypass = [c for c in rep["changes"] if c["kind"] == "guard_bypassed"]
    assert bypass and bypass[0]["via_hunks"]
    assert set(bypass[0]["via_hunks"]) <= hunk_ids
