# Feature: platform-aware Joern install

**For:** anyone running `witness doctor --install` on macOS, Linux or Windows. On Windows this means Windows with Git for Windows (Git Bash) installed.

## Goal

`witness doctor --install --yes` installs the right Joern build on any 64-bit macOS, Linux or Windows machine, and every platform uses a shell script:

| Host | Installer | Run with |
|---|---|---|
| macOS, Linux | upstream `joern-install.sh` (kept, as today) | `sh` |
| Windows | new `install-joern-windows.sh`, shipped with witness | Git Bash's `bash.exe` |
| Either, when that shell or `unzip` is missing | pure-Python fallback (`urllib`, `hashlib`, `zipfile`): the platform-agnostic path | Python |

Joern v4.0.684 publishes six builds, all 64-bit:

| OS | x86_64 | arm64 |
|---|---|---|
| macOS | `joern-cli-macos-x86_64.zip` | `joern-cli-macos-arm64.zip` |
| Linux | `joern-cli-linux-x86_64.zip` | `joern-cli-linux-arm64.zip` |
| Windows | `joern-cli-windows-x86_64.zip` | `joern-cli-windows-arm64.zip` |

Each zip has a `.sha512` file next to it. There is no 32-bit build.

Why Windows gets its own script: upstream `joern-install.sh` detects the platform from `uname -s`. Under Git Bash that is `MINGW64_NT-…`, which falls through to `linux-x86_64`. The script also maps any non-arm CPU, 32-bit included, to x86_64, without warning. So witness detects the platform in Python first and refuses 32-bit or unknown hosts before any script runs.

### Portable JDK (default)

Joern runs on Java and needs **JDK 21** (from Joern's README). Users shouldn't have to install it themselves. So by default, `doctor --install --yes` also installs a portable Eclipse Temurin JDK 21 into `~/.witness/jdk/`. It skips this when a `java` of major version 21 or newer is already available. Nothing is installed system-wide, and `PATH` and the registry are left alone.

| OS | Temurin archive (from `api.adoptium.net/v3/assets/latest/21/hotspot`) | `java` inside |
|---|---|---|
| macOS x64 / aarch64 | `OpenJDK21U-jdk_<arch>_mac_hotspot_*.tar.gz` | `jdk-21*/Contents/Home/bin/java` |
| Linux x64 / aarch64 | `OpenJDK21U-jdk_<arch>_linux_hotspot_*.tar.gz` | `jdk-21*/bin/java` |
| Windows x64 / aarch64 | `OpenJDK21U-jdk_<arch>_windows_hotspot_*.zip` | `jdk-21*\bin\java.exe` |

- **Download:** about 200 MB. The API response gives the link, size and **sha256**, which is checked before anything is extracted. Extraction goes to a temp directory and is renamed into place.
- **Joern uses it:** when witness runs Joern, the engine's subprocess environment sets `JAVA_HOME` to the portable JDK and puts its `bin` first on `PATH`. Joern's launchers then pick it up without the user changing anything.
- **Overrides:**
  - `WITNESS_JAVA_HOME` forces a specific JDK.
  - `doctor --install --yes --system-java` skips the portable JDK and requires the system one.
- **The JDK install is Python, on every OS** (`urllib`, `hashlib`, `tarfile`/`zipfile`). Only Joern itself goes through the shell scripts. `tarfile` extraction uses `filter="data"`, so a crafted archive can't write outside the target.

## What changes for the user

- `witness doctor` prints a new row:
  - on a supported host: `platform: windows-x86_64 (joern-cli-windows-x86_64.zip)`
  - on a 32-bit host: `platform: 32-bit x86 — unsupported, Joern ships 64-bit builds only`
- On Windows, `witness doctor` also prints a `git-bash` row, with the path it found or `not found`.
- `witness doctor --install` (dry run) names the installer it would run, the asset (about 1.8 GB) and the destination. It downloads nothing.
- `witness doctor --install --yes` runs that installer non-interactively into `~/.witness/joern`. Joern lands in `~/.witness/joern/joern-cli/`.
- `install-joern-windows.sh` is POSIX `sh` run under Git Bash. It:
  - detects the architecture from `PROCESSOR_ARCHITECTURE` / `PROCESSOR_ARCHITEW6432` (`AMD64`, `ARM64`) and refuses anything else;
  - accepts `--asset=` and `--install-dir=`;
  - downloads with `curl -L`, which Git for Windows ships;
  - checks `sha512sum` against the `.sha512` file;
  - extracts with `unzip` if present, else Windows' own `tar.exe` (bsdtar reads zip), into a temp directory, then moves it into place;
  - exits non-zero on any failure.

  It can be run on its own: `bash install-joern-windows.sh --install-dir="$HOME/joern"`.
- **Finding Git Bash on Windows:** `git --exec-path` gives `<Git>\mingw64\libexec\git-core`, and Git Bash is `<Git>\bin\bash.exe`. witness checks that path, then `%ProgramFiles%\Git\bin\bash.exe`. It never uses `C:\Windows\System32\bash.exe`, which is WSL's bash.
- **The Python fallback:** downloads, checks the sha512, extracts to a temp directory, renames it into place, and runs `chmod +x` on POSIX.
- **After install:** `witness analyze` finds Joern in `~/.witness/joern/joern-cli` even when it isn't on `PATH`; on Windows that means the `.bat` launchers. `WITNESS_JOERN_HOME` overrides the location.
- **Unknown OS or CPU, or 32-bit:** exit 3, with the supported builds listed and no download.

## Acceptance checks

1. On this Mac (arm64), `witness doctor --install` names `joern-install.sh` and `joern-cli-macos-arm64.zip`, and downloads nothing.
2. With platform detection faked, each of the six OS/arch pairs maps to the right asset. `AMD64`, `x86_64`, `aarch64`, `ARM64` and `arm64` are all recognised.
3. With 32-bit faked (`i686`, `x86`, `armv7l`, or a 32-bit Python), `--install --yes` exits 3, says only 64-bit builds exist, and runs no installer.
4. With Windows faked and Git Bash found, `--install --yes` runs `<Git>\bin\bash.exe <pkg>/scripts/install-joern-windows.sh --install-dir=<dest> --asset=joern-cli-windows-x86_64.zip`.
   - The path comes from `git --exec-path`.
   - A `System32\bash.exe` on `PATH` is ignored.
   - With no Git Bash found, the install uses the Python fallback.
5. With macOS or Linux faked, it runs `sh joern-install.sh --install-dir=<dest> --without-plugins`, as today. With `sh` or `unzip` missing, it uses the Python fallback.
6. `install-joern-windows.sh` itself, run here under `sh` with `PROCESSOR_ARCHITECTURE=AMD64` and a local file server or `file://` URL serving a tiny zip:
   - a good sha512 installs;
   - a bad sha512 exits non-zero and leaves nothing behind;
   - `PROCESSOR_ARCHITECTURE=x86` exits non-zero.
7. The Python fallback refuses a mismatched sha512 and leaves nothing behind. A matching tiny zip installs, and `joern` resolves from `~/.witness/joern/joern-cli` without `PATH`.
8. With no `java`, or with `java` 17 faked, `doctor --install` (dry run) lists the Temurin 21 archive for this platform and `~/.witness/jdk`. With `java` 21 faked, it lists no JDK.
9. A faked Temurin download with a bad sha256 is refused and leaves nothing behind. A tiny matching tarball installs, and `joern_home.java_home()` returns it. That works for the macOS `Contents/Home` layout and the flat Linux and Windows layout.
10. With a portable JDK present, the engine's `_env()` sets `JAVA_HOME` to it and puts its `bin` first on `PATH`. `WITNESS_JAVA_HOME` wins over both. `doctor`'s `java` row shows `portable JDK 21 (~/.witness/jdk/…)`.
11. `--system-java` installs no JDK, and fails with exit 3 if no `java` 21 or newer exists.
12. Existing tests pass, with the doctor tests updated.

## Code map

- **Entry point:** `src/witness/cli.py:42`, the `doctor` subparser (`--install`, `--yes`). At `cli.py:71` it calls `doctor.run(install, yes)`.
- **`src/witness/doctor.py`:**
  - `INSTALL_URL`: the `joern-install.sh` URL, kept.
  - `check()`: runs `shutil.which` for each tool.
  - `_download_and_run(dest)`: the upstream script runner. It switches to `sh`.
  - `install(yes, runner)`: the test seam.
  - `run()`: exit 0 or 3.
- **`src/witness/pipeline.py:31`:** `_default_build` checks `which("joern")` and `which("joern-parse")`, and raises `JoernMissing` if either is missing.
- **`src/witness/engines/joern.py:82,103,108`:** calls bare `"joern"` and `"joern-parse"`.
- **`engines/joern.py:65`:** `_env()` builds the subprocess environment by copying `os.environ` minus proxies. This is the seam for `JAVA_HOME` and `PATH`.
- **Tests:**
  - `tests/test_cli.py:104` and `:163` are the doctor tests; they monkeypatch `urlopen` and `subprocess.run`.
  - `tests/test_joern.py:93` is skipped without Joern.
- **Packaging:** hatchling. `src/witness/scripts/install-joern-windows.sh` ships as package data and is found with `importlib.resources`.
- **Frozen interfaces:**
  - the CLI flags;
  - `doctor.run(do_install, yes, out)` and its exit codes 0 and 3;
  - `install(yes, runner=...)`;
  - `INSTALL_URL`;
  - `JoernMissing` and exit code 4.
- **Conventions:** standard library only, no new dependencies; tests run with `uv run pytest`.

## Design

- **New `src/witness/joern_home.py`:**
  - `detect() -> Platform(os, arch, asset)`. It reads `platform.system()` and `platform.machine()`, and checks `struct.calcsize("P") == 4` to catch 32-bit Python. It raises `UnsupportedPlatform`.
  - `asset_url(asset)`.
  - `home()`: `WITNESS_JOERN_HOME`, otherwise `~/.witness/joern`.
  - `resolve(tool)`: `which(tool)`, otherwise `home()/joern-cli/<tool>` (`.bat` on Windows).
  - `git_bash()`: the lookup described above. It returns a Path or None.
- **`doctor.choose_installer(plat) -> (name, runner)`:**
  - POSIX with `sh` and `unzip` uses `_download_and_run`.
  - Windows with `git_bash()` uses `_run_git_bash`.
  - Anything else uses `_python_install`.
  - `install()` calls `detect()` first, so a 32-bit host stops before any runner.
- **New `src/witness/scripts/install-joern-windows.sh`:**
  - POSIX `sh`, with `set -eu`.
  - The base URL can be overridden with `JOERN_BASE_URL`, for tests.
- **Engine and pipeline:** both use `joern_home.resolve()`.
- **New `src/witness/jdk.py`:**
  - `java_major(java)` parses `java -version`.
  - `find_java()` looks at `WITNESS_JAVA_HOME`, then the portable JDK, then the system `java`.
  - `temurin_asset(plat)` makes one call to the Adoptium API and returns the name, link, size and sha256.
  - `install_portable(dest, asset, fetch=...)` downloads, checks the sha256 and extracts safely. `fetch` is injectable for tests.
  - `java_home()` points at `Contents/Home` on macOS.
- **`engines/joern._env()`:** adds `JAVA_HOME` and the `PATH` prefix when `jdk.find_java()` returns a JDK witness manages, or a `WITNESS_JAVA_HOME`.
- **`doctor`:** the `java` row reports the version and where it came from. `install()` runs the JDK step first, then Joern. The dry run lists both.

## Prototype scope

The sandbox holds `joern_home.py`, the installer selection in `doctor`, `install-joern-windows.sh` and the Python fallback. Its tests cover checks 1 to 7. Platforms, `git --exec-path` and tool lookups are faked. A tiny local zip is served with both a good and a bad sha512, and the Windows script runs for real under this Mac's `sh`. There is no real 1.8 GB download. The try-out is a dry-run `doctor --install` on this machine.

## Integration outline

1. `joern_home.py` (detection, resolution, Git Bash lookup), plus `tests/test_joern_home.py`.
2. `install-joern-windows.sh` as package data (hatch include), plus a test that runs the script itself.
3. `doctor.py`: installer selection, the Git Bash runner and the Python fallback, plus updated doctor tests.
4. Joern lookup in `pipeline.py` and `engines/joern.py`, plus a seam test that an installed home resolves without `PATH`.
5. `jdk.py`, plus the JDK step in `doctor`, plus the `_env()` seam in `engines/joern.py`, with `tests/test_jdk.py`.
6. README Install section: the portable JDK, `WITNESS_JAVA_HOME` and `--system-java`; a per-platform table, a note that Windows needs Git for Windows, 64-bit only, and no `PATH` step needed.

## Decisions

- **Ruling (user):** keep `joern-install.sh` for macOS and Linux.
- **Ruling (user):** Windows uses Git Bash, not PowerShell.
- **Ruling:** Windows needs its own `install-joern-windows.sh`. Upstream's `uname` check installs `linux-x86_64` under MINGW.
- **Ruling:** find Git Bash through `git --exec-path`, never through `PATH`, so WSL's `System32\bash.exe` is never picked.
- **Ruling:** a pure-Python installer is the platform-agnostic fallback when Git Bash, `sh` or `unzip` is missing.
- **Ruling:** witness checks the platform before any script runs.
- **Ruling:** pin to `releases/latest`; a `--version` flag is out of scope.
- **Ruling:** run affected tests only at finish: `tests/test_cli.py`, `tests/test_joern_home.py` and `tests/test_joern.py`.
- **Ruling (user):** install a portable Temurin JDK 21 under `~/.witness/jdk` by default. `--system-java` opts out.
- **Ruling:** don't use winget. It has no Joern package, and a portable JDK covers Java on every OS.
- **Ruling:** the JDK install is pure Python on every OS, checked against Adoptium's sha256, and extracted with `tarfile` `filter="data"`.
- **Ruling:** affected tests include `tests/test_jdk.py`.
