import subprocess
from pathlib import Path

from witness import acquire

DIFF = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -3,1 +3,1 @@\n-a\n+b\n"


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()


def make_repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("1\n")
    git(r, "add", ".")
    git(r, "commit", "-qm", "c1")
    return r


def test_parse_hunks_basic():
    (h,) = acquire.parse_hunks(DIFF)
    assert (h.old_path, h.new_path, h.old_start, h.old_len, h.new_start, h.new_len) == (
        "x.py", "x.py", 3, 1, 3, 1,
    )
    assert h.text == "-a\n+b"


def test_hunk_id_stable():
    a = acquire.parse_hunks(DIFF)
    b = acquire.parse_hunks(DIFF)
    assert [h.id for h in a] == [h.id for h in b]
    assert len(a[0].id) == 10


def test_rename_map():
    assert acquire.renames("R087 a.py b.py\n") == {"a.py": "b.py"}
    d = "diff --git a/a.py b/b.py\nsimilarity index 87%\nrename from a.py\nrename to b.py\n"
    assert acquire.renames(d) == {"a.py": "b.py"}


def test_unicode_path():
    d = 'diff --git "a/\\303\\251.py" "b/\\303\\251.py"\n--- "a/\\303\\251.py"\n+++ "b/\\303\\251.py"\n@@ -1 +1 @@\n-a\n+b\n'
    (h,) = acquire.parse_hunks(d)
    assert h.new_path == "é.py"
    assert h.old_len == 1


def test_host_for():
    assert acquire.host_for("git@bitbucket.org:acme/shop.git") == "bitbucket"
    assert acquire.host_for("https://github.com/acme/shop") == "github"


def test_checkout_reuses_worktree(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    sha = git(repo, "rev-parse", "HEAD")
    cache = tmp_path / "cache"
    p1 = acquire.checkout(repo, sha, cache)
    assert (p1 / "a.txt").exists()
    calls = []
    real = acquire._run
    monkeypatch.setattr(acquire, "_run", lambda argv, cwd=None: (calls.append(argv), real(argv, cwd))[1])
    p2 = acquire.checkout(repo, sha, cache)
    assert p1 == p2
    assert not any("worktree" in a for a in calls)


def test_merge_base_used(tmp_path):
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "feat")
    (repo / "b.txt").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "feat")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    (repo / "c.txt").write_text("y\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "main2")
    info = acquire.resolve_pr("main..feat", repo)
    assert info.base_sha == base
    assert info.head_sha == head


def test_run_redacts_credentials(monkeypatch):
    import pytest
    from witness.shared import EnvError

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_SECRET123")
    url = "https://user:pw0rd@example.com/r.git"
    with pytest.raises(EnvError) as ei:
        acquire._run(["git", "ls-remote", url])
    assert "pw0rd" not in str(ei.value)
    assert acquire.redact("fatal: ghp_SECRET123 x") == "fatal: *** x"
    out = acquire.redact("Authorization: Bearer abc.def\nAuthorization: Basic Zm9v\nhttps://u:t@h/x")
    assert "abc.def" not in out and "Zm9v" not in out and "u:t" not in out


def test_renames_with_spaces():
    assert acquire.renames("R087\told name.py\tnew name.py\n") == {"old name.py": "new name.py"}
    d = "rename from a b.py\nrename to c d.py\n"
    assert acquire.renames(d) == {"a b.py": "c d.py"}
    assert acquire.renames("R100 a.py b.py\n") == {"a.py": "b.py"}
