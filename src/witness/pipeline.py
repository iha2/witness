"""Pipeline (T15)."""

from collections.abc import Callable
from pathlib import Path

from witness.shared import NotImplementedStub


def analyze(
    repo: Path,
    ref: str | None,
    base: str | None,
    head: str | None,
    no_llm: bool,
    on_event: Callable[[dict], None],
) -> dict:
    raise NotImplementedStub("T15", "pipeline.analyze")
