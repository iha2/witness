"""Graph model (T2): typed nodes and edges, reachability, SQLite persistence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

Key = tuple[str, str, str, str]
Span = tuple[str, int, int]


@dataclass
class Node:
    id: int
    kind: str
    key: Key
    span: Span | None
    attrs: dict[str, str] = field(default_factory=dict)


class Graph:
    """Directed multigraph. Node ids are dense ints in insertion order."""

    def __init__(self) -> None:
        self.nodes: list[Node] = []
        self.edges: list[tuple[int, int, str]] = []
        self._out: dict[int, list[tuple[int, str]]] = {}
        self._keys: dict[Key, int] = {}
        self._edge_set: set[tuple[int, int, str]] = set()

    def add_node(
        self,
        kind: str,
        key: Key,
        span: Span | None,
        attrs: dict[str, str],
    ) -> int:
        nid = len(self.nodes)
        key = tuple(key)  # type: ignore[assignment]
        self.nodes.append(Node(nid, kind, key, span, dict(attrs)))
        self._out[nid] = []
        self._keys.setdefault(key, nid)
        return nid

    def add_edge(self, src: int, dst: int, kind: str) -> None:
        for n in (src, dst):
            if not 0 <= n < len(self.nodes):
                raise KeyError(n)
        e = (src, dst, kind)
        if e in self._edge_set:
            return
        self._edge_set.add(e)
        self.edges.append(e)
        self._out[src].append((dst, kind))

    def by_key(self, key: Key) -> int | None:
        return self._keys.get(tuple(key))  # type: ignore[arg-type]

    def has_path(self, src: int, dst: int, kinds: set[str], without: set[int]) -> bool:
        if src in without or dst in without:
            return False
        if src == dst:
            return True
        seen = {src}
        stack = [src]
        while stack:
            cur = stack.pop()
            for nxt, k in self._out.get(cur, ()):
                if k not in kinds or nxt in without or nxt in seen:
                    continue
                if nxt == dst:
                    return True
                seen.add(nxt)
                stack.append(nxt)
        return False


def save_graph(g: Graph, path: Path) -> None:
    path = Path(path)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, kind TEXT, key TEXT, span TEXT, attrs TEXT)"
        )
        con.execute("CREATE TABLE edges (seq INTEGER PRIMARY KEY, src INT, dst INT, kind TEXT)")
        con.executemany(
            "INSERT INTO nodes VALUES (?,?,?,?,?)",
            [
                (
                    n.id,
                    n.kind,
                    json.dumps(list(n.key)),
                    json.dumps(list(n.span)) if n.span else None,
                    json.dumps(n.attrs, sort_keys=True),
                )
                for n in g.nodes
            ],
        )
        con.executemany(
            "INSERT INTO edges (src, dst, kind) VALUES (?,?,?)", g.edges
        )
        con.commit()
    finally:
        con.close()


def load_graph(path: Path) -> Graph:
    con = sqlite3.connect(Path(path))
    try:
        g = Graph()
        for _id, kind, key, span, attrs in con.execute(
            "SELECT id, kind, key, span, attrs FROM nodes ORDER BY id"
        ):
            s = json.loads(span) if span else None
            g.add_node(kind, tuple(json.loads(key)), tuple(s) if s else None, json.loads(attrs))
        for src, dst, kind in con.execute("SELECT src, dst, kind FROM edges ORDER BY seq"):
            g.add_edge(src, dst, kind)
        return g
    finally:
        con.close()
