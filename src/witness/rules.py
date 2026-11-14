"""Check and sink rules (T7): tag graph nodes as source, sink, guard or external.

A rule pack is YAML mapping a role to glob patterns over call names:

    guard: [validate_*, "*.sanitize"]
    sink: ["db.*.insert"]

Patterns without a dot also match the last dotted segment of a name.
"""

from fnmatch import fnmatchcase
from pathlib import Path

import yaml

from witness.model import Graph
from witness.shared import UsageError

ROLES: tuple[str, ...] = ("guard", "sink", "source", "external")
_RULES_DIR = Path(__file__).parent / "rules"
_FAMILIES = {
    "python": "python",
    "py": "python",
    "java": "java",
    "kotlin": "java",
    "scala": "java",
    "javascript": "javascript",
    "typescript": "javascript",
    "js": "javascript",
    "ts": "javascript",
    "c": "c",
    "cpp": "c",
    "c++": "c",
    "go": "go",
}

Rules = dict[str, list[str]]


def load_rule_file(path: Path) -> Rules:
    """Read one YAML rule file; raise UsageError naming the file when it is invalid."""
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as e:
        raise UsageError(f"cannot read rules file {path}: {e}") from e
    except yaml.YAMLError as e:
        raise UsageError(f"invalid yaml in rules file {path}: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise UsageError(f"rules file {path} must be a mapping of role to patterns")
    rules: Rules = {}
    for role, pats in data.items():
        if role not in ROLES:
            raise UsageError(f"rules file {path}: unknown role {role!r}")
        if isinstance(pats, str):
            pats = [pats]
        if not isinstance(pats, list) or not all(isinstance(p, str) for p in pats):
            raise UsageError(f"rules file {path}: role {role!r} needs a list of strings")
        rules[role] = list(pats)
    return rules


def _merge(into: Rules, extra: Rules) -> None:
    for role, pats in extra.items():
        into.setdefault(role, []).extend(pats)


def _matches(patterns: list[str], name: str) -> bool:
    last = name.rsplit(".", 1)[-1]
    for pat in patterns:
        if fnmatchcase(name, pat):
            return True
        if "." not in pat and fnmatchcase(last, pat):
            return True
    return False


def _role_of(name: str, repo_rules: Rules, pack: Rules) -> str | None:
    # Repo rules are checked first so they override the packs.
    for rules in (repo_rules, pack):
        for role in ROLES:
            if _matches(rules.get(role, []), name):
                return role
    return None


def _nodes(g: Graph):
    nodes = g.nodes
    return nodes() if callable(nodes) else nodes


def tag(g: Graph, lang: str, extra: Path | None) -> Graph:
    """Set attrs["role"] on CALL and EXTERNAL nodes whose name matches a rule; return g."""
    pack: Rules = {}
    for fname in ("common", _FAMILIES.get(lang.lower())):
        if fname and (_RULES_DIR / f"{fname}.yaml").exists():
            _merge(pack, load_rule_file(_RULES_DIR / f"{fname}.yaml"))
    repo_rules: Rules = {}
    if extra is not None and extra.exists():
        repo_rules = load_rule_file(extra)
    for node in _nodes(g):
        if node.kind not in ("CALL", "EXTERNAL", "METHOD"):
            continue
        name = node.attrs.get("name", "")
        if not name:
            continue
        role = _role_of(name, repo_rules, pack)
        if role is not None:
            node.attrs["role"] = role
    return g
