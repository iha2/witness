"""Joern engine: build a WGM Graph from a scoped checkout (T6)."""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from witness.model import Graph
from witness.shared import EnvError

_EDGE_KINDS = {"CALL": "calls", "REACHING_DEF": "dflow"}
_PROXY = re.compile(r"^(https?|ftp|all)_proxy$", re.I)
_TIMEOUT = 600
_SCRIPT = Path(__file__).with_name("joern") / "export.sc"


class ExportFormatError(EnvError, ValueError):
    """Malformed joern export; an EnvError (exit 3) and a ValueError."""


def parse_export(jsonl: str) -> Graph:
    """Parse export.sc JSONL into a Graph (nodes first, then edges)."""
    g = Graph()
    ids: dict[int, int] = {}
    edges: list[dict] = []
    for n, line in enumerate(jsonl.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (ValueError, RecursionError) as exc:
            raise ExportFormatError(f"joern export line {n}: invalid JSON") from exc
        if not isinstance(rec, dict):
            raise ExportFormatError(f"joern export line {n}: record is not an object")
        try:
            if rec.get("t") == "node":
                span = None
                if rec.get("line"):
                    span = (rec["path"], int(rec["line"][0]), int(rec["line"][1]))
                key = (rec["path"], rec["qname"], str(rec.get("sig", "")), "")
                attrs = {"name": str(rec.get("name") or rec["qname"])}
                if rec.get("fingerprint"):
                    attrs["fingerprint"] = str(rec["fingerprint"])
                ids[rec["id"]] = g.add_node(rec["kind"], key, span, attrs)
            elif rec.get("t") == "edge":
                rec["src"], rec["dst"], rec["kind"]
                edges.append((n, rec))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ExportFormatError(
                f"joern export line {n}: malformed record ({type(exc).__name__}: {exc})"
            ) from exc
    for n, e in edges:
        try:
            if e["src"] in ids and e["dst"] in ids:
                kind = _EDGE_KINDS.get(e["kind"], str(e["kind"]).lower())
                g.add_edge(ids[e["src"]], ids[e["dst"]], kind)
        except TypeError as exc:
            raise ExportFormatError(f"joern export line {n}: malformed edge") from exc
    return g


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not _PROXY.match(k)}


def _run(argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv, env=_env(), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        raise EnvError("joern timeout") from exc
    except FileNotFoundError as exc:
        raise EnvError("joern not found") from exc


def joern_version() -> str:
    """Return the installed Joern version string."""
    proc = _run(["joern", "--version"], 60)
    out = (proc.stdout or proc.stderr).strip()
    if proc.returncode != 0 or not out:
        raise EnvError("joern version unavailable")
    return out.splitlines()[-1].strip()


class JoernEngine:
    def __init__(self, timeout: int = _TIMEOUT) -> None:
        self.timeout = timeout

    def build(self, checkout: Path, files: list[str], heap: str) -> Graph:
        with tempfile.TemporaryDirectory(prefix="witness-joern-") as tmp:
            src = Path(tmp) / "src"
            for rel in files:
                dst = src / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.symlink_to((Path(checkout) / rel).resolve())
            cpg = Path(tmp) / "cpg.bin"
            out = Path(tmp) / "export.jsonl"
            heap_arg = f"-J-Xmx{heap}"
            p = _run(["joern-parse", heap_arg, str(src), "--output", str(cpg)], self.timeout)
            if p.returncode != 0 or not cpg.exists():
                raise EnvError(f"joern-parse failed: {p.stderr.strip()[:200]}")
            p = _run(
                [
                    "joern", heap_arg, "--script", str(_SCRIPT),
                    "--param", f"cpgFile={cpg}", "--param", f"out={out}",
                ],
                self.timeout,
            )
            if p.returncode != 0 or not out.exists():
                raise EnvError(f"joern export failed: {p.stderr.strip()[:200]}")
            return parse_export(out.read_text())
