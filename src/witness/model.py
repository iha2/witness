"""Graph model (T2)."""

from witness.shared import NotImplementedStub


class Graph:
    """Graph model: signatures only in Wave 0."""

    def add_node(
        self,
        kind: str,
        key: tuple[str, str, str, str],
        span: tuple[str, int, int] | None,
        attrs: dict[str, str],
    ) -> int:
        raise NotImplementedStub("T2", "model.Graph.add_node")

    def has_path(self, src: int, dst: int, kinds: set[str], without: set[int]) -> bool:
        raise NotImplementedStub("T2", "model.Graph.has_path")
