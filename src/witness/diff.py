"""Flow diff (T9)."""

from witness.model import Graph
from witness.shared import FlowChange, Match, NotImplementedStub


def flow_diff(base: Graph, head: Graph, m: Match) -> list[FlowChange]:
    raise NotImplementedStub("T9", "diff.flow_diff")
