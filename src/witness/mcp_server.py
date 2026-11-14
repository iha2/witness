"""MCP server (T16): stdio tools over one analysis job, every response under 8k tokens."""

import json
import threading
from collections.abc import Callable
from pathlib import Path

from witness import explain as explain_mod
from witness.shared import FlowChange, Hunk

MAX_TOKENS = 8000
PAGE = 20
PATH_PAGE = 5
_TEXT_CAP = 4000


def _tokens(obj: object) -> int:
    return len(json.dumps(obj, default=str)) // 4


def _cap(resp: dict) -> dict:
    """Shrink a response until it fits the token cap."""
    if _tokens(resp) <= MAX_TOKENS:
        return resp
    resp = dict(resp)
    for k, v in list(resp.items()):
        if isinstance(v, str) and len(v) > _TEXT_CAP:
            resp[k] = v[:_TEXT_CAP]
            resp["truncated"] = True
    for k in ("items", "paths", "changes"):
        v = resp.get(k)
        if isinstance(v, list):
            while v and _tokens(resp) > MAX_TOKENS:
                v = v[: len(v) // 2]
                resp[k] = v
                resp["truncated"] = True
    if _tokens(resp) > MAX_TOKENS:
        return {"error": "response too large", "truncated": True}
    return resp


class _Job:
    def __init__(self) -> None:
        self.phase = "calls"
        self.events: list[dict] = []
        self.report: dict | None = None
        self.error: str | None = None
        self.explanations: dict[str, dict] = {}
        self.done = threading.Event()


class WitnessService:
    """Tool implementations; plain methods so they can be tested without a transport."""

    def __init__(self, cache: Path, analyze_fn: Callable[..., dict]) -> None:
        self.cache = Path(cache)
        self.analyze_fn = analyze_fn
        self.jobs: dict[str, _Job] = {}
        self._latest: str | None = None
        self._lock = threading.Lock()

    def _job(self, job: str | None) -> _Job | None:
        return self.jobs.get(job or self._latest or "")

    def analyze(self, repo: str = ".", ref: str | None = None, base: str | None = None,
                head: str | None = None, no_llm: bool = True) -> dict:
        with self._lock:
            jid = f"j{len(self.jobs) + 1}"
            j = _Job()
            self.jobs[jid] = j
            self._latest = jid

        def on_event(ev: dict) -> None:
            j.events.append(ev)
            j.phase = "deep"

        def run() -> None:
            try:
                j.report = self.analyze_fn(Path(repo), ref, base, head, no_llm, on_event)
            except Exception as e:  # reported through overview
                j.error = f"{type(e).__name__}: {e}"
            finally:
                j.phase = "done"
                j.done.set()

        threading.Thread(target=run, daemon=True).start()
        return {"job": jid}

    def overview(self, job: str | None = None) -> dict:
        j = self._job(job)
        if j is None:
            return _cap({"error": "unknown job"})
        out: dict = {"phase": j.phase}
        if j.error:
            out["error"] = j.error
        if j.report is not None:
            r = j.report
            out.update(hunks=len(r.get("hunks", [])), changes=len(r.get("changes", [])),
                       coverage=r.get("coverage", {}),
                       explained=len(j.explanations))
        elif j.events:
            out["events"] = len(j.events)
        return _cap(out)

    def _report(self, job: str | None) -> tuple[_Job | None, dict | None]:
        j = self._job(job)
        return j, (j.report if j else None)

    def list_hunks(self, page: int = 0, job: str | None = None) -> dict:
        j, r = self._report(job)
        if r is None:
            return _cap({"error": "no report yet", "phase": j.phase if j else None})
        hunks = r.get("hunks", [])
        lo = max(page, 0) * PAGE
        items = [{"id": h.get("id"), "path": h.get("new_path") or h.get("path"),
                  "new_start": h.get("new_start"), "new_len": h.get("new_len")}
                 for h in hunks[lo: lo + PAGE]]
        nxt = page + 1 if lo + PAGE < len(hunks) else None
        return _cap({"items": items, "next": nxt})

    def _find(self, hid: str, job: str | None) -> tuple[_Job | None, dict | None, dict | None]:
        j, r = self._report(job)
        if r is None:
            return j, None, None
        for h in r.get("hunks", []):
            if h.get("id") == hid:
                return j, r, h
        return j, r, None

    def _changes(self, r: dict, hid: str) -> list[dict]:
        return [c for c in r.get("changes", []) if hid in (c.get("via_hunks") or [])]

    def hunk(self, id: str, job: str | None = None) -> dict:
        j, r, h = self._find(id, job)
        if r is None:
            return _cap({"error": "no report yet"})
        if h is None:
            return _cap({"error": f"unknown hunk: {id}"})
        out = {"hunk": h, "changes": self._changes(r, id)[:PATH_PAGE],
               "explanation": (j.explanations.get(id) if j else None)
               or (r.get("explanations") or {}).get(id)}
        return _cap(out)

    def paths(self, id: str, page: int = 0, job: str | None = None) -> dict:
        _, r, h = self._find(id, job)
        if r is None:
            return _cap({"error": "no report yet"})
        if h is None:
            return _cap({"error": f"unknown hunk: {id}"})
        cs = self._changes(r, id)
        lo = max(page, 0) * PATH_PAGE
        nxt = page + 1 if lo + PATH_PAGE < len(cs) else None
        return _cap({"paths": cs[lo: lo + PATH_PAGE], "next": nxt})

    def graph(self, id: str, format: str = "mermaid", job: str | None = None) -> dict:
        _, r, h = self._find(id, job)
        if r is None:
            return _cap({"error": "no report yet"})
        if h is None:
            return _cap({"error": f"unknown hunk: {id}"})
        cs = self._changes(r, id)
        if format == "json":
            body, ext = json.dumps(cs, indent=1), "json"
        else:
            lines = ["graph LR"]
            for i, c in enumerate(cs):
                lines.append(f'  s{i}["{c.get("src")}"] -->|{c.get("kind")}| t{i}["{c.get("sink")}"]')
            body, ext = "\n".join(lines) + "\n", "mmd"
        self.cache.mkdir(parents=True, exist_ok=True)
        path = self.cache / f"graph-{id}.{ext}"
        path.write_text(body)
        return _cap({"path": str(path), "format": ext, "changes": len(cs)})

    def submit_explanation(self, id: str, json_text: str, job: str | None = None) -> dict:
        j, r, h = self._find(id, job)
        if r is None or j is None:
            return _cap({"error": "no report yet"})
        if h is None:
            return _cap({"error": f"unknown hunk: {id}"})
        try:
            expl = json.loads(json_text)
        except ValueError:
            return _cap({"ok": False, "problems": ["bad-json"]})
        hunk = Hunk(
            id=id, old_path=h.get("old_path", ""), new_path=h.get("new_path", h.get("path", "")),
            old_start=h.get("old_start", 0), old_len=h.get("old_len", 0),
            new_start=h.get("new_start", 0), new_len=h.get("new_len", 0), text=h.get("text", ""))
        changes = [FlowChange(
            kind=c.get("kind", ""), src=c.get("src", ""), sink=c.get("sink", ""),
            guard=c.get("guard"), base_path=c.get("base_path"), head_path=c.get("head_path"),
            via_hunks=list(c.get("via_hunks") or []), confidence=float(c.get("confidence", 1.0)))
            for c in self._changes(r, id)]
        pack = explain_mod.build_pack(hunk, changes, (r.get("slices") or {}).get(id, {}))
        problems = explain_mod.validate(expl, pack)
        if problems:
            return _cap({"ok": False, "problems": problems})
        j.explanations[id] = expl
        return {"ok": True, "problems": []}


def create_server(cache: Path, analyze_fn: Callable[..., dict] | None = None) -> object:
    """Build the MCP server; `server.service` exposes the tool implementations."""
    from mcp.server.mcpserver import MCPServer

    if analyze_fn is None:
        from witness import pipeline

        def analyze_fn(*a, **k):  # late binding so the pipeline can be swapped
            return pipeline.analyze(*a, **k)

    svc = WitnessService(cache, analyze_fn)
    server = MCPServer("witness")
    for name in ("analyze", "overview", "list_hunks", "hunk", "paths", "graph",
                 "submit_explanation"):
        server.add_tool(getattr(svc, name), name=name)
    server.service = svc  # type: ignore[attr-defined]
    return server


def main() -> None:
    create_server(Path.home() / ".cache" / "witness" / "mcp").run()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
