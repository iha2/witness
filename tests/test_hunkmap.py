from witness.hunkmap import map_hunks
from witness.model import Graph
from witness.shared import Hunk, hunk_id


def mk(path, old_start, old_len, new_start, new_len, text, old_path=None):
    return Hunk(hunk_id(path, old_start, new_start, text), old_path or path, path,
                old_start, old_len, new_start, new_len, text)


def graph(path, methods):
    g = Graph()
    g.add_node("MODULE", (path, path, "", ""), (path, 1, 1000), {})
    for name, s, e in methods:
        g.add_node("METHOD", (path, name, "1", ""), (path, s, e), {})
    return g


def test_added_lines_map_to_head_method():
    base = graph("a.py", [("a.f", 30, 60)])
    head = graph("a.py", [("a.f", 30, 62)])
    h = mk("a.py", 41, 0, 41, 2, "@@ -40,0 +41,2 @@\n+x = 1\n+y = 2\n")
    assert map_hunks([h], base, head, {})[h.id] == [1]


def test_removed_lines_use_base_spans():
    base = graph("a.py", [("a.f", 1, 10), ("a.g", 11, 30)])
    head = graph("a.py", [("a.f", 1, 20), ("a.g", 21, 30)])
    h = mk("a.py", 12, 1, 12, 0, "@@ -12,1 +12,0 @@\n-gone = 1\n")
    # line 12 is in a.g in base (id 2); head has no added lines, so only base ids appear
    assert map_hunks([h], base, head, {})[h.id] == [2]


def test_removed_lines_follow_rename():
    base = graph("old.py", [("m.f", 1, 10)])
    head = graph("new.py", [("m.f", 1, 10)])
    h = mk("new.py", 3, 1, 3, 0, "@@ -3,1 +3,0 @@\n-x\n", old_path="old.py")
    assert map_hunks([h], base, head, {"old.py": "new.py"})[h.id] == [1]


def test_module_level_hunk_maps_to_module():
    base = graph("a.py", [("a.f", 30, 60)])
    head = graph("a.py", [("a.f", 30, 60)])
    h = mk("a.py", 2, 0, 2, 1, "@@ -1,0 +2,1 @@\n+import os\n")
    assert map_hunks([h], base, head, {}) == {h.id: [0]}


def test_by_side_separates_head_and_base():
    from witness.hunkmap import map_hunks_by_side
    base = graph("a.py", [("a.f", 1, 10), ("a.g", 11, 30)])
    head = graph("a.py", [("a.f", 1, 20), ("a.g", 21, 30)])
    h = mk("a.py", 12, 1, 5, 1, "@@ -12,1 +5,1 @@\n-old\n+new\n")
    r = map_hunks_by_side([h], base, head, {})[h.id]
    assert r == {"head": [1], "base": [2]}
    assert map_hunks([h], base, head, {})[h.id] == [1, 2]


def test_unknown_file_maps_to_nothing():
    h = mk("z.py", 1, 0, 1, 1, "@@ -0,0 +1,1 @@\n+x\n")
    assert map_hunks([h], Graph(), Graph(), {}) == {h.id: []}
