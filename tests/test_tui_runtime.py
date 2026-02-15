from __future__ import annotations

from pathlib import Path

import pytest

from whisper_local import tui_runtime


def _touch_executable(path: Path) -> None:
    """
    Create a minimal executable shell script at the given path for use in tests.
    
    Creates parent directories if necessary, writes a small script that exits with status 0, and sets the file's permissions to be executable.
    
    Parameters:
        path (Path): Destination path where the executable stub will be created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)


def test_resolve_runtime_uses_env_override(tmp_path: Path) -> None:
    binary = tmp_path / "bin" / "whisper-local-tui"
    _touch_executable(binary)

    runtime = tui_runtime.resolve_tui_runtime(
        env={tui_runtime.ENV_TUI_BIN: str(binary)},
        sys_executable=str(tmp_path / "python"),
        cli_file=tmp_path / "src" / "whisper_local" / "cli.py",
        current_dir=tmp_path,
    )

    assert runtime.mode == "env-override"
    assert runtime.command == [str(binary)]
    assert runtime.cwd == binary.parent


def test_resolve_runtime_fails_for_invalid_env_override(tmp_path: Path) -> None:
    bad_binary = tmp_path / "bin" / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        tui_runtime.resolve_tui_runtime(
            env={tui_runtime.ENV_TUI_BIN: str(bad_binary)},
            sys_executable=str(tmp_path / "python"),
            cli_file=tmp_path / "src" / "whisper_local" / "cli.py",
            current_dir=tmp_path,
        )


def test_resolve_runtime_uses_packaged_binary_near_python(tmp_path: Path) -> None:
    python_bin = tmp_path / "libexec" / "bin" / "python3.12"
    _touch_executable(python_bin)
    binary = tmp_path / "libexec" / "bin" / "whisper-local-tui"
    _touch_executable(binary)

    runtime = tui_runtime.resolve_tui_runtime(
        env={},
        sys_executable=str(python_bin),
        cli_file=tmp_path / "libexec" / "lib" / "python3.12" / "site-packages" / "whisper_local" / "cli.py",
        current_dir=tmp_path,
    )

    assert runtime.mode == "packaged"
    assert runtime.command == [str(binary)]


def test_resolve_runtime_dev_mode_needs_bun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "tui" / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tui" / "src" / "index.tsx").write_text("export {};\n", encoding="utf-8")

    monkeypatch.setattr(tui_runtime.shutil, "which", lambda _: None)

    with pytest.raises(FileNotFoundError):
        tui_runtime.resolve_tui_runtime(
            env={tui_runtime.ENV_DEV_USE_BUN: "1"},
            sys_executable=str(tmp_path / "python"),
            cli_file=repo_root / "src" / "whisper_local" / "cli.py",
            current_dir=repo_root,
        )


def test_resolve_runtime_dev_mode_uses_local_tui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "tui" / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tui" / "src" / "index.tsx").write_text("export {};\n", encoding="utf-8")

    monkeypatch.setattr(tui_runtime.shutil, "which", lambda _: "/usr/local/bin/bun")

    runtime = tui_runtime.resolve_tui_runtime(
        env={tui_runtime.ENV_DEV_USE_BUN: "1"},
        sys_executable=str(tmp_path / "python"),
        cli_file=repo_root / "src" / "whisper_local" / "cli.py",
        current_dir=repo_root,
    )

    assert runtime.mode == "dev-bun"
    assert runtime.command == ["bun", "src/index.tsx"]
    assert runtime.cwd == repo_root / "tui"