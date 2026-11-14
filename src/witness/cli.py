"""witness command line (T15). Exit codes: 0 ok, 2 usage, 3 environment, 4 partial."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from witness import doctor, pipeline, render
from witness.shared import EnvError, UsageError, WitnessError


_SECRET_ENVS = ("GITHUB_TOKEN", "GH_TOKEN", "WITNESS_BITBUCKET_TOKEN", "ANTHROPIC_API_KEY")


def _redact(msg: str) -> str:
    """Strip credentials from text bound for stderr: env secrets and URL userinfo."""
    for name in _SECRET_ENVS:
        val = os.environ.get(name)
        if val:
            msg = msg.replace(val, "***")
    return re.sub(r"(\w+://)[^/\s@]+@", r"\1***@", msg)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # noqa: ANN201
        raise UsageError(message)


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog="witness")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    a = sub.add_parser("analyze")
    a.add_argument("ref", nargs="?")
    a.add_argument("--base")
    a.add_argument("--head")
    a.add_argument("--repo", default=".")
    a.add_argument("--no-llm", action="store_true")
    a.add_argument("--format", default="text",
                   choices=["json", "md", "text", "sarif", "annotations"])
    d = sub.add_parser("doctor")
    d.add_argument("--install", action="store_true")
    d.add_argument("--yes", action="store_true")
    return p


def _emit(report: dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(report, indent=2))
    elif fmt == "md":
        print(render.to_markdown(report))
    elif fmt == "sarif":
        print(json.dumps(render.to_sarif(report), indent=2))
    elif fmt == "annotations":
        print(render.to_annotations(report))
    else:
        print(render.to_text(report))


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["eval"]:
        from witness import eval as eval_mod

        return eval_mod.main(argv[1:], pipeline.analyze)
    try:
        args = _parser().parse_args(argv)
        if args.cmd == "doctor":
            return doctor.run(args.install, args.yes)
        if bool(args.base) != bool(args.head):
            raise UsageError("--base and --head go together")
        if not args.ref and not args.base:
            raise UsageError("give a PR ref or --base and --head")
        report = pipeline.analyze(Path(args.repo), args.ref, args.base, args.head,
                                  args.no_llm, lambda e: None)
    except SystemExit as exc:  # --help
        return int(exc.code or 0)
    except UsageError as exc:
        print(f"usage error: {_redact(str(exc))}", file=sys.stderr)
        return 2
    except EnvError as exc:
        print(f"environment error: {_redact(str(exc))}", file=sys.stderr)
        return 3
    except WitnessError as exc:
        print(f"error: {_redact(str(exc))}", file=sys.stderr)
        return 3
    if report["coverage"].get("partial"):
        if args.format == "json":
            print(json.dumps(report, indent=2))
            print("deep analysis unavailable: run witness doctor", file=sys.stderr)
        else:
            for h in report["hunks"]:
                print(f"{h['id']}  {h['path']}:{h['start']}-{h['end']}")
            print("deep analysis unavailable (Joern missing): run witness doctor")
        return 4
    _emit(report, args.format)
    return 0
