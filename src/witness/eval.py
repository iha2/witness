"""Evaluation harness (T18): score flow changes against a corpus, enforce release gates."""

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import yaml

GATES = {"precision": 0.90, "recall": 0.75, "refactor_fp_rate": 0.05, "grounded": 0.98}


def _key(c: dict) -> tuple[str, str, str]:
    return (c["kind"], c["src"], c["sink"])


def score(expected: list[dict], found: list[dict]) -> dict:
    """Precision and recall of found against expected, by (kind, src, sink)."""
    exp = {_key(c) for c in expected}
    got = {_key(c) for c in found}
    tp = len(exp & got)
    return {
        "precision": tp / len(got) if got else 0.0,
        "recall": tp / len(exp) if exp else 1.0,
        "tp": tp,
        "found": len(got),
        "expected": len(exp),
    }


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def make_repo(dest: Path, base: dict[str, str], head: dict[str, str]) -> tuple[str, str]:
    """Create a two-commit git repo; return (base_sha, head_sha)."""
    dest.mkdir(parents=True, exist_ok=True)
    _git(dest, "init", "-q")
    shas = []
    for files in (base, head):
        for p in [p for p in dest.rglob("*") if p.is_file() and ".git" not in p.parts]:
            p.unlink()
        for name, text in files.items():
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            (dest / name).write_text(text)
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "--allow-empty", "-m", "c")
        shas.append(_git(dest, "rev-parse", "HEAD"))
    return shas[0], shas[1]


def load_mutation(mutations_dir: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"witness_eval_mut_{name}", mutations_dir / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _grounded(report: dict) -> tuple[int, int]:
    """(grounded, total) over hunks that carry an explanation."""
    ok = total = 0
    for h in report.get("hunks", []):
        e = h.get("explanation")
        if not isinstance(e, dict):
            continue
        total += 1
        if e.get("grounded", not e.get("errors")):
            ok += 1
    return ok, total


def _default_analyze() -> Callable:
    from witness import pipeline

    return pipeline.analyze


def run(
    corpus: Path,
    lang: str | None = None,
    analyze: Callable | None = None,
    workdir: Path | None = None,
) -> dict:
    """Run the corpus; return per-language metrics, gate results and an overall pass flag."""
    corpus = Path(corpus)
    analyze = analyze or _default_analyze()
    entries = yaml.safe_load(corpus.read_text())["entries"]
    work = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="witness-eval-"))
    acc: dict[str, dict] = {}
    for e in entries:
        if lang and e["lang"] != lang:
            continue
        repo = work / e["id"]
        if "mutation" in e:
            mod = load_mutation(corpus.parent / "mutations", e["mutation"])
            base, head = make_repo(repo, mod.BASE_FILES, mod.HEAD_FILES)
            expected = list(mod.EXPECTED)
        else:
            repo, base, head = Path(e["repo"]), e["base"], e["head"]
            expected = e.get("expected", [])
        report = analyze(repo, None, base, head, True, lambda ev: None)
        found = report.get("changes", [])
        a = acc.setdefault(
            e["lang"],
            {"tp": 0, "found": 0, "expected": 0, "refactors": 0, "refactor_fp": 0, "g_ok": 0, "g_total": 0, "n": 0},
        )
        a["n"] += 1
        if e.get("type") == "refactor":
            a["refactors"] += 1
            a["refactor_fp"] += 1 if found else 0
        else:
            s = score(expected, found)
            a["tp"] += s["tp"]
            a["found"] += s["found"]
            a["expected"] += s["expected"]
        g_ok, g_total = _grounded(report)
        a["g_ok"] += g_ok
        a["g_total"] += g_total

    langs: dict[str, dict] = {}
    passed = True
    for lg, a in acc.items():
        m = {
            "n": a["n"],
            "precision": a["tp"] / a["found"] if a["found"] else 0.0,
            "recall": a["tp"] / a["expected"] if a["expected"] else 1.0,
            "refactor_fp_rate": a["refactor_fp"] / a["refactors"] if a["refactors"] else 0.0,
            "grounded": a["g_ok"] / a["g_total"] if a["g_total"] else 1.0,
        }
        m["gates"] = {
            "precision": m["precision"] >= GATES["precision"],
            "recall": m["recall"] >= GATES["recall"],
            "refactor_fp_rate": m["refactor_fp_rate"] <= GATES["refactor_fp_rate"],
            "grounded": m["grounded"] >= GATES["grounded"],
        }
        m["passed"] = all(m["gates"].values())
        passed = passed and m["passed"]
        langs[lg] = m
    return {"languages": langs, "passed": passed and bool(langs)}


def main(argv: list[str] | None = None, analyze: Callable | None = None) -> int:
    """Exit 0 when all gates pass, 1 when any gate fails, 2 on usage error."""
    ap = argparse.ArgumentParser(prog="witness-eval")
    ap.add_argument("--corpus", default="eval/corpus.yaml")
    ap.add_argument("--lang")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    result = run(Path(args.corpus), args.lang, analyze)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result["passed"] else 1
