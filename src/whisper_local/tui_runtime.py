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
    candidate_dirs = [current_dir / "tui"]
    for parent in cli_file_path.parents:
        candidate_dirs.append(parent / "tui")

    for candidate in candidate_dirs:
        if (candidate / "src" / "index.tsx").exists():
            return candidate
    return None


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False
