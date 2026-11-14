import asyncio
import json

from witness.mcp_server import MAX_TOKENS, create_server

HUNK_TEXT = "@@ -1,1 +1,2 @@\n+validate_coupon(x)\n"


def fake_analyze(repo, ref, base, head, no_llm, on_event):
    on_event({"type": "hunks", "hunks": []})
    hunks = [{"id": f"h{i:03d}", "old_path": "a.py", "new_path": "a.py", "old_start": 1,
              "old_len": 1, "new_start": 1, "new_len": 2, "text": HUNK_TEXT * 50}
             for i in range(45)]
    changes = [{"kind": "guard_bypassed", "src": "request.coupon", "sink": "db.insert",
                "guard": "validate_coupon", "base_path": "a", "head_path": "b",
                "via_hunks": ["h000"], "confidence": 0.9}] * 30
    return {"schema": "witness.report.v1", "hunks": hunks, "changes": changes,
            "coverage": {"engine": "joern"},
            "slices": {"h000": {"nodes": [{"name": "a.f", "span": "a.py:1-9", "role": "enclosing"}]}}}


def started():
    srv = create_server(__import__("pathlib").Path("."), fake_analyze)
    return srv, srv.service


def run_job(tmp_path):
    srv = create_server(tmp_path, fake_analyze)
    svc = srv.service
    jid = svc.analyze(".", None, "HEAD~1", "HEAD", True)["job"]
    svc.jobs[jid].done.wait(5)
    return svc, jid


def test_job_lifecycle(tmp_path):
    svc, jid = run_job(tmp_path)
    assert jid == "j1"
    ov = svc.overview(jid)
    assert ov["phase"] == "done" and ov["hunks"] == 45


def test_server_registers_tools(tmp_path):
    srv = create_server(tmp_path, fake_analyze)
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert {"analyze", "overview", "list_hunks", "hunk", "paths", "graph",
            "submit_explanation"} <= names


def test_paging_and_unknown_hunk(tmp_path):
    svc, jid = run_job(tmp_path)
    p0 = svc.list_hunks(0)
    assert len(p0["items"]) == 20 and p0["next"] == 1
    assert svc.list_hunks(2)["next"] is None
    assert "unknown hunk" in svc.hunk("nope")["error"]
    assert "unknown hunk" in svc.paths("nope")["error"]


def test_unknown_hunk_error(tmp_path):
    svc, _ = run_job(tmp_path)
    assert svc.submit_explanation("zzz", "{}")["error"].startswith("unknown hunk")


def test_every_response_under_8k_tokens(tmp_path):
    svc, jid = run_job(tmp_path)
    resps = [svc.overview(), svc.list_hunks(0), svc.hunk("h000"), svc.paths("h000"),
             svc.paths("h000", 1), svc.graph("h000"), svc.graph("h000", "json")]
    for r in resps:
        assert len(json.dumps(r)) // 4 <= MAX_TOKENS
    assert svc.graph("h000")["path"].endswith(".mmd")


def test_submit_explanation_validates(tmp_path):
    svc, _ = run_job(tmp_path)
    bad = json.dumps({"title": "t", "explanation": [{"text": "It does a thing.", "cites": []}]})
    r = svc.submit_explanation("h000", bad)
    assert r["ok"] is False and "no-cite" in r["problems"]
    good = json.dumps({"title": "Guard bypass", "explanation": [
        {"text": "Guard `validate_coupon` is bypassed between `request.coupon` and `db.insert`.",
         "cites": ["F2"]}]})
    r = svc.submit_explanation("h000", good)
    assert r == {"ok": True, "problems": []}
    assert svc.hunk("h000")["explanation"]["title"] == "Guard bypass"
