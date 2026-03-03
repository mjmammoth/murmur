from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ENV_TUI_BIN = "MURMUR_TUI_BIN"
ENV_DEV_USE_BUN = "MURMUR_DEV_USE_BUN"
TUI_EXECUTABLE = "murmur-tui"


@dataclass(frozen=True)
class TuiRuntime:
    mode: str
    command: list[str]
    cwd: Path | None


def resolve_tui_runtime(
    env: Mapping[str, str] | None = None,
    *,
    sys_executable: str | None = None,
    cli_file: str | Path | None = None,
    current_dir: str | Path | None = None,
) -> TuiRuntime:
    """
    Determine how to run the Whisper Local TUI and return a descriptor describing the chosen command and working directory.

    Parameters:
        env (Mapping[str, str] | None): Environment variables to consult; defaults to the process environment.
        sys_executable (str | None): Path to the Python interpreter used to derive packaged-executable candidate locations; defaults to sys.executable.
        cli_file (str | Path | None): Path to the current CLI file used to derive relative candidate locations; defaults to this module's file.
        current_dir (str | Path | None): Current working directory used when searching for a local development TUI; defaults to Path.cwd().

    Returns:
        TuiRuntime: An immutable descriptor with `mode` set to one of:
          - "env-override": executable path taken from the environment override,
          - "packaged": a discovered packaged TUI executable,
          - "dev-bun": a local TUI run via Bun; `command` and `cwd` reflect the chosen runtime.
    """
    resolved_env = dict(os.environ if env is None else env)
    resolved_sys_executable = Path(sys_executable or sys.executable).resolve()
    resolved_cli_file = Path(cli_file or __file__).resolve()
    resolved_current_dir = Path(current_dir or Path.cwd()).resolve()

    configured_bin = resolved_env.get(ENV_TUI_BIN, "").strip()
    if configured_bin:
        configured_path = Path(configured_bin).expanduser()
        if not _is_executable_file(configured_path):
            raise FileNotFoundError(
                f"{ENV_TUI_BIN} is set but not executable: {configured_path}"
            )
        return TuiRuntime(
            mode="env-override",
            command=[str(configured_path)],
            cwd=configured_path.parent,
        )

    for candidate in _packaged_tui_candidates(
        sys_executable_path=resolved_sys_executable,
        cli_file_path=resolved_cli_file,
    ):
        if _is_executable_file(candidate):
            return TuiRuntime(
                mode="packaged",
                command=[str(candidate)],
                cwd=candidate.parent,
            )

    if resolved_env.get(ENV_DEV_USE_BUN) == "1":
        dev_tui_dir = _find_local_tui_directory(
            cli_file_path=resolved_cli_file,
            current_dir=resolved_current_dir,
        )
        if dev_tui_dir is None:
            raise FileNotFoundError(
                f"{ENV_DEV_USE_BUN}=1 but local TUI source was not found."
            )
        if shutil.which("bun") is None:
            raise FileNotFoundError(
                f"{ENV_DEV_USE_BUN}=1 but bun is not available on PATH."
            )
        return TuiRuntime(
            mode="dev-bun",
            command=["bun", "src/index.tsx"],
            cwd=dev_tui_dir,
        )

    raise FileNotFoundError(
        f"Unable to locate packaged TUI runtime executable '{TUI_EXECUTABLE}'. "
        f"Set {ENV_TUI_BIN} to an executable path. "
        f"For local contributors, set {ENV_DEV_USE_BUN}=1 to run from ./tui with bun."
    )


def _packaged_tui_candidates(
    *,
    sys_executable_path: Path,
    cli_file_path: Path,
) -> list[Path]:
    """
    Produce an ordered list of candidate filesystem paths where a packaged TUI executable may be located.

    Parameters:
        sys_executable_path (Path): Path to the Python interpreter; used to derive interpreter-relative candidate locations.
        cli_file_path (Path): Path to the CLI source file; used to derive project-relative candidate locations.

    Returns:
        list[Path]: Unique candidate paths (in search order) for the packaged TUI executable.
    """
    exe_dir = sys_executable_path.parent
    candidates = [
        exe_dir / TUI_EXECUTABLE,
        exe_dir.parent / "bin" / TUI_EXECUTABLE,
        exe_dir.parent.parent / "bin" / TUI_EXECUTABLE,
        cli_file_path.parent / TUI_EXECUTABLE,
    ]

    for parent in cli_file_path.parents:
        if parent.name == "libexec":
            candidates.append(parent / "bin" / TUI_EXECUTABLE)

    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved_candidate = candidate.expanduser()
        if resolved_candidate in seen:
            continue
        seen.add(resolved_candidate)
        unique_candidates.append(resolved_candidate)
    return unique_candidates


def _find_local_tui_directory(*, cli_file_path: Path, current_dir: Path) -> Path | None:
    """
    Locate a local development TUI directory containing a valid source entry point.

    Searches current_dir / "tui" first, then for each parent of cli_file_path searches parent / "tui" and returns the first directory that contains src/index.tsx.

    Parameters:
        cli_file_path (Path): Path to the CLI file used to derive parent search locations.
        current_dir (Path): Current working directory to check for a local TUI.

    Returns:
        Path | None: Path to the first matching "tui" directory, or `None` if no directory containing src/index.tsx is found.
    """
    candidate_dirs = [current_dir / "tui"]
    for parent in cli_file_path.parents:
        candidate_dirs.append(parent / "tui")

    for candidate in candidate_dirs:
        if (candidate / "src" / "index.tsx").exists():
            return candidate
    return None


def _is_executable_file(path: Path) -> bool:
    """
    Check whether a given filesystem path points to an executable file.

    Parameters:
        path (Path): Filesystem path to test.

    Returns:
        bool: `True` if `path` exists as a file and the current process has execute permission for it, `False` otherwise (including when an `OSError` occurs).
    """
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False
