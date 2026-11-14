"""Hunk mapper (T10, design section 8).

Added and changed lines map to head METHOD nodes (head node ids). Removed lines map to
base METHOD nodes (base node ids, found through the old path / rename map). Lines outside
any method map to the file's MODULE node. Result: hunk id -> sorted node ids.
"""

import re

from witness.model import Graph
from witness.shared import Hunk

_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines(h: Hunk) -> tuple[list[int], list[int]]:
    """(removed old line numbers, added new line numbers) parsed from the hunk text."""
    removed: list[int] = []
    added: list[int] = []
    old, new = h.old_start, h.new_start
    for line in h.text.splitlines():
        m = _HEADER.match(line)
        if m:
            old, new = int(m.group(1)), int(m.group(2))
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(new)
            new += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(old)
            old += 1
        elif line.startswith("\\"):
            continue
        else:
            old += 1
            new += 1
    if not removed and not added:  # no diff markers: fall back to the whole ranges
        removed = list(range(h.old_start, h.old_start + h.old_len))
        added = list(range(h.new_start, h.new_start + h.new_len))
    return removed, added


def _index(g: Graph) -> tuple[dict[str, list[tuple[int, int, int]]], dict[str, int]]:
    methods: dict[str, list[tuple[int, int, int]]] = {}
    modules: dict[str, int] = {}
    for n in g.nodes:
        if n.kind == "MODULE":
            modules.setdefault(n.span[0] if n.span else n.key[0], n.id)
        elif n.kind == "METHOD" and n.span is not None:
            path, start, end = n.span
            methods.setdefault(path, []).append((start, end, n.id))
    return methods, modules


def _lookup(lines: list[int], paths: list[str], idx: tuple[dict, dict]) -> set[int]:
    methods, modules = idx
    out: set[int] = set()
    path = next((p for p in paths if p in methods or p in modules), None)
    if path is None:
        return out
    for ln in lines:
        best = None
        for start, end, nid in methods.get(path, ()):
            if start <= ln <= end and (best is None or end - start < best[0]):
                best = (end - start, nid)
        if best is not None:
            out.add(best[1])
        elif path in modules:
            out.add(modules[path])
    return out


def map_hunks_by_side(
    hunks: list[Hunk], base: Graph, head: Graph, renames: dict[str, str]
) -> dict[str, dict[str, list[int]]]:
    """Hunk id -> {"head": head node ids (added lines), "base": base node ids (removed lines)}.

    Head and base ids live in different graphs, so callers that look nodes up must use the
    side-specific list.
    """
    bidx, hidx = _index(base), _index(head)
    inverse = {v: k for k, v in renames.items()}
    result: dict[str, dict[str, list[int]]] = {}
    for h in hunks:
        removed, added = changed_lines(h)
        head_ids = _lookup(added, [h.new_path], hidx)
        old_paths = [p for p in (h.old_path, inverse.get(h.new_path)) if p]
        base_ids = _lookup(removed, old_paths, bidx)
        result[h.id] = {"head": sorted(head_ids), "base": sorted(base_ids)}
    return result


def map_hunks(
    hunks: list[Hunk], base: Graph, head: Graph, renames: dict[str, str]
) -> dict[str, list[int]]:
    """Flat, side-less union of head and base ids (kept for existing callers).

    The ids come from two different graphs; use map_hunks_by_side to tell them apart.
    """
    return {
        hid: sorted(set(s["head"]) | set(s["base"]))
        for hid, s in map_hunks_by_side(hunks, base, head, renames).items()
    }
