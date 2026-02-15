from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ENV_TUI_BIN = "WHISPER_LOCAL_TUI_BIN"
ENV_DEV_USE_BUN = "WHISPER_LOCAL_DEV_USE_BUN"
TUI_EXECUTABLE = "whisper-local-tui"


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
    Resolve how to run the Whisper Local TUI and return an execution descriptor.
    
    Parameters:
        env (Mapping[str, str] | None): Optional environment mapping to use instead of os.environ.
        sys_executable (str | None): Optional path to the Python interpreter used to derive packaged candidates.
        cli_file (str | Path | None): Optional path to the calling CLI file used to locate packaged or local TUI assets.
        current_dir (str | Path | None): Optional current working directory used when searching for a local development TUI.
    
    Returns:
        TuiRuntime: Descriptor with `mode` ("env-override", "packaged", or "dev-bun"), `command` to execute, and `cwd` for the process.
    
    Raises:
        FileNotFoundError: If ENV_TUI_BIN is set but not an executable file.
        FileNotFoundError: If ENV_DEV_USE_BUN=1 but a local TUI source directory is not found.
        FileNotFoundError: If ENV_DEV_USE_BUN=1 but `bun` is not available on PATH.
        FileNotFoundError: If no packaged executable is found and no valid override or dev configuration applies.
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
        "Unable to locate packaged TUI runtime executable 'whisper-local-tui'. "
        f"Set {ENV_TUI_BIN} to an executable path. "
        f"For local contributors, set {ENV_DEV_USE_BUN}=1 to run from ./tui with bun."
    )


def _packaged_tui_candidates(
    *,
    sys_executable_path: Path,
    cli_file_path: Path,
) -> list[Path]:
    """
    Assemble ordered candidate filesystem paths where a packaged TUI executable may be located.
    
    Returns:
        list[Path]: Unique, user-expanded candidate paths in search order to check for the packaged TUI executable; duplicates are removed while preserving the first-seen order.
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
    Locate a local TUI project directory that contains a TUI source entry at `src/index.tsx`.
    
    Parameters:
        cli_file_path (Path): Path of the calling CLI file used to search its parent directories.
        current_dir (Path): Current working directory to check first for a local `tui` directory.
    
    Returns:
        Path | None: The path to the first matching `tui` directory that contains `src/index.tsx`, or `None` if no such directory is found.
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
    Check whether the given path points to an executable file.
    
    Returns:
        True if the path exists as a file and is executable, False otherwise.
    """
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False