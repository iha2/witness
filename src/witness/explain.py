"""Explainer and validator (T11)."""

from collections.abc import Callable

from witness.shared import NotImplementedStub


def validate(expl: dict, pack: dict) -> list[str]:
    raise NotImplementedStub("T11", "explain.validate")


def explain(pack: dict, llm: Callable[[str], str] | None) -> dict:
    raise NotImplementedStub("T11", "explain.explain")
