import subprocess
from pathlib import Path

from witness import eval as ev

CORPUS = Path(__file__).parent.parent / "eval" / "corpus.yaml"


def c(kind="guard_bypassed", src="a", sink="b"):
    return {"kind": kind, "src": src, "sink": sink}


def test_score_perfect():
    s = ev.score([c()], [c()])
    assert s["precision"] == 1.0 and s["recall"] == 1.0


def test_score_half():
    s = ev.score([c(), c("added_flow")], [c(), c("rerouted")])
    assert s["precision"] == 0.5 and s["recall"] == 0.5


def test_score_empty_found():
    s = ev.score([c()], [])
    assert s["precision"] == 0.0 and s["recall"] == 0.0


def test_mutation_remove_validator(tmp_path):
    mod = ev.load_mutation(CORPUS.parent / "mutations", "remove_validator")
    assert mod.EXPECTED[0]["kind"] == "guard_bypassed"
    base, head = ev.make_repo(tmp_path / "r", mod.BASE_FILES, mod.HEAD_FILES)
    old = subprocess.run(["git", "show", f"{base}:app.py"], cwd=tmp_path / "r", capture_output=True, text=True).stdout
    new = subprocess.run(["git", "show", f"{head}:app.py"], cwd=tmp_path / "r", capture_output=True, text=True).stdout
    assert "validate(user_input)" in old and "validate(user_input)" not in new


def perfect_analyze(repo, ref, base, head, no_llm, on_event):
    name = repo.name
    if name == "mut-remove-validator":
        ch = [c("guard_bypassed", "handle", "run_query")]
    elif name == "mut-new-caller":
        ch = [c("new_caller", "extra", "helper")]
    else:
        ch = []
    return {"schema": "witness.report.v1", "hunks": [{"explanation": {"errors": []}}], "changes": ch, "coverage": {}}


def noisy_analyze(repo, ref, base, head, no_llm, on_event):
    r = perfect_analyze(repo, ref, base, head, no_llm, on_event)
    if repo.name == "refactor-rename-local":
        r["changes"] = [c("added_flow", "x", "y")]
    return r


def test_run_passes_gates(tmp_path):
    r = ev.run(CORPUS, None, perfect_analyze, tmp_path)
    assert r["passed"] and r["languages"]["python"]["precision"] == 1.0


def test_run_lang_filter(tmp_path):
    assert ev.run(CORPUS, "rust", perfect_analyze, tmp_path)["languages"] == {}


def test_gate_fail_exit_nonzero(capsys):
    assert ev.main(["--corpus", str(CORPUS)], perfect_analyze) == 0
    assert ev.main(["--corpus", str(CORPUS)], noisy_analyze) != 0


def test_ungrounded_fails_gate(tmp_path):
    def bad(repo, *a):
        r = perfect_analyze(repo, *a)
        r["hunks"] = [{"explanation": {"errors": ["x"]}}]
        return r

    r = ev.run(CORPUS, None, bad, tmp_path)
    assert not r["passed"] and r["languages"]["python"]["grounded"] == 0.0
