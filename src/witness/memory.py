"""Review memory: which finding ids were already shown for a PR."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def compare(prev: list[str], cur: dict[str, tuple[str, str]]) -> dict:
    prev_set = set(prev)
    return {
        "new": [key for key in cur if key not in prev_set],
        "resolved": [key for key in prev if key not in cur],
        "seen": [key for key in cur if key in prev_set],
    }


def save(path: Path, head_sha: str, ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"head": head_sha, "ids": ids}, fh)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return list(json.loads(text)["ids"])
