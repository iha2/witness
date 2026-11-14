"""Scope finder (T5)."""

from pathlib import Path

from witness.shared import Hunk, NotImplementedStub, Scope


def find_scope(
    repo: Path,
    base: str,
    head: str,
    hunks: list[Hunk],
    hops: int,
    max_files: int,
) -> Scope:
    raise NotImplementedStub("T5", "scope.find_scope")
