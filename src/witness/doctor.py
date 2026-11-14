"""witness doctor: check the environment, optionally install Joern (T15)."""

import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

INSTALL_URL = "https://github.com/joernio/joern/releases/latest/download/joern-install.sh"


def check() -> list[tuple[str, bool, str]]:
    rows = []
    for tool in ("git", "java", "joern", "joern-parse", "gh"):
        path = shutil.which(tool)
        rows.append((tool, path is not None, path or "not found"))
    return rows


def _download_and_run(dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "joern-install.sh"
        with urllib.request.urlopen(INSTALL_URL, timeout=60) as resp:  # noqa: S310
            script.write_bytes(resp.read())
        subprocess.run(["bash", str(script), f"--install-dir={dest}", "--without-plugins"], check=True)


def install(yes: bool, runner: Callable[[Path], None] = _download_and_run) -> str:
    """Install Joern only when `yes` is set; otherwise download nothing."""
    dest = Path.home() / ".witness" / "joern"
    if not yes:
        return f"Would download {INSTALL_URL} and install Joern to {dest}. Re-run with --yes to proceed."
    runner(dest)
    return f"Joern installed to {dest}. Add {dest} to PATH."


def run(do_install: bool, yes: bool, out=sys.stdout) -> int:
    rows = check()
    for name, ok, detail in rows:
        print(f"{'ok ' if ok else 'MISSING'} {name}: {detail}", file=out)
    if do_install:
        print(install(yes), file=out)
        if yes:
            rows = check()
    required = {"git", "java", "joern", "joern-parse"}
    return 0 if all(ok for n, ok, _ in rows if n in required) else 3
