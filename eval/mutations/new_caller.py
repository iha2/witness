"""Mutation: insert a new caller of an existing function. Expect new_caller."""

NAME = "new_caller"
LANG = "python"
EXPECTED = [{"kind": "new_caller", "src": "extra", "sink": "helper"}]

BASE = "def helper(x):\n    return x + 1\n\n\ndef main():\n    return helper(1)\n"
HEAD = BASE + "\n\ndef extra():\n    return helper(2)\n"

BASE_FILES = {"app.py": BASE}
HEAD_FILES = {"app.py": HEAD}
