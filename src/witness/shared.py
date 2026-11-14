"""Shared error and data types (plan Global constraints)."""

import hashlib
from dataclasses import dataclass


class NotImplementedStub(NotImplementedError):
    """A Wave 0 stub was called before its owning task was built."""

    def __init__(self, task_id: str, name: str) -> None:
        super().__init__(f"{task_id}: {name} is not implemented yet")


class WitnessError(Exception):
    """Base error for witness."""


class EnvError(WitnessError):
    """Environment problem (exit code 3)."""


class UsageError(WitnessError):
    """Bad invocation (exit code 2)."""


@dataclass(frozen=True)
class Hunk:
    id: str
    old_path: str
    new_path: str
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    text: str


@dataclass(frozen=True)
class PRInfo:
    host: str
    base_sha: str
    head_sha: str
    title: str
    body: str


@dataclass(frozen=True)
class Scope:
    files: list[str]
    unanalysed: list[str]


@dataclass(frozen=True)
class FlowChange:
    kind: str
    src: str
    sink: str
    guard: str | None
    base_path: str | None
    head_path: str | None
    via_hunks: list[str]
    confidence: float


Match = dict[int, tuple[int, str, float]]

# Rank order: earlier kinds rank higher.
FLOW_KINDS: tuple[str, ...] = (
    "guard_bypassed",
    "guard_added",
    "added_flow",
    "removed_flow",
    "rerouted",
    "new_caller",
    "lost_caller",
)


def hunk_id(new_path: str, old_start: int, new_start: int, text: str) -> str:
    """Stable 10-hex-char id for a hunk."""
    raw = f"{new_path}|{old_start}|{new_start}|{text}".encode()
    return hashlib.sha1(raw).hexdigest()[:10]
