"""Mutation: remove a validator call. Expect guard_bypassed."""

NAME = "remove_validator"
LANG = "python"
EXPECTED = [{"kind": "guard_bypassed", "src": "handle", "sink": "run_query"}]

BASE = '''def validate(x):
    if "'" in x:
        raise ValueError(x)
    return x


def run_query(q):
    return q


def handle(user_input):
    clean = validate(user_input)
    return run_query(clean)
'''
HEAD = BASE.replace("clean = validate(user_input)", "clean = user_input")

BASE_FILES = {"app.py": BASE}
HEAD_FILES = {"app.py": HEAD}
