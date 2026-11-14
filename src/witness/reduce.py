"""Slice reducer (T10)."""

from witness.model import Graph
from witness.shared import FlowChange, NotImplementedStub


def reduce_slice(
    head: Graph,
    seeds: list[int],
    changes: list[FlowChange],
    budget: int,
) -> dict:
    raise NotImplementedStub("T10", "reduce.reduce_slice")
