"""Shared error and data types for the Wave 0 stub tree."""

from dataclasses import dataclass


class NotImplementedStub(NotImplementedError):
    """A Wave 0 stub was called before its owning task was built."""

    def __init__(self, task_id: str, name: str) -> None:
        super().__init__(f"{task_id}: {name} is not implemented yet")


@dataclass
class Hunk:
    old_path: str
    new_path: str
    old_start: int
    old_len: int
    new_start: int
    new_len: int


@dataclass
class Scope:
    files: list[str]
    unanalysed: list[str]
    changed_names: list[str]


@dataclass
class FlowChange:
    kind: str
    src: str
    sink: str
    guard: str | None = None


Match = dict[int, tuple[int, str, float]]
