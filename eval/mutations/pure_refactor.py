"""Mutation: rename a local variable. Expect zero flow changes."""

NAME = "pure_refactor"
LANG = "python"
EXPECTED: list[dict] = []

BASE_FILES = {"app.py": "def f(a):\n    total = a + 1\n    return total\n"}
HEAD_FILES = {"app.py": "def f(a):\n    result = a + 1\n    return result\n"}
