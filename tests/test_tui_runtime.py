from __future__ import annotations

from pathlib import Path

import pytest

from whisper_local import tui_runtime


def _touch_executable(path: Path) -> None:
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


def test_resolve_runtime_prefers_env_over_packaged(tmp_path: Path) -> None:
    """Test that ENV_TUI_BIN takes precedence over packaged binary."""
    env_binary = tmp_path / "custom" / "whisper-local-tui"
    _touch_executable(env_binary)

    # Create a packaged binary too
    packaged_binary = tmp_path / "bin" / "whisper-local-tui"
    _touch_executable(packaged_binary)

    runtime = tui_runtime.resolve_tui_runtime(
        env={tui_runtime.ENV_TUI_BIN: str(env_binary)},
        sys_executable=str(tmp_path / "bin" / "python"),
        cli_file=tmp_path / "src" / "whisper_local" / "cli.py",
        current_dir=tmp_path,
    )

    assert runtime.mode == "env-override"
    assert runtime.command == [str(env_binary)]
    assert runtime.cwd == env_binary.parent


def test_resolve_runtime_no_runtime_available_raises(tmp_path: Path) -> None:
    """Test that resolve_tui_runtime raises when no runtime found."""
    with pytest.raises(FileNotFoundError, match="Unable to locate packaged TUI runtime"):
        tui_runtime.resolve_tui_runtime(
            env={},
            sys_executable=str(tmp_path / "python"),
            cli_file=tmp_path / "src" / "whisper_local" / "cli.py",
            current_dir=tmp_path,
        )


def test_resolve_runtime_packaged_multiple_candidates(tmp_path: Path) -> None:
    """Test that resolve_tui_runtime finds packaged binary in multiple locations."""
    # Create binary in the python bin directory
    python_bin = tmp_path / "venv" / "bin" / "python3.12"
    _touch_executable(python_bin)
    binary = tmp_path / "venv" / "bin" / "whisper-local-tui"
    _touch_executable(binary)

    runtime = tui_runtime.resolve_tui_runtime(
        env={},
        sys_executable=str(python_bin),
        cli_file=tmp_path / "venv" / "lib" / "python3.12" / "site-packages" / "whisper_local" / "cli.py",
        current_dir=tmp_path,
    )

    assert runtime.mode == "packaged"
    assert runtime.command == [str(binary)]


def test_resolve_runtime_packaged_in_libexec(tmp_path: Path) -> None:
    """Test that resolve_tui_runtime finds packaged binary in libexec/bin."""
    python_bin = tmp_path / "libexec" / "bin" / "python3.12"
    _touch_executable(python_bin)

    binary = tmp_path / "libexec" / "bin" / "whisper-local-tui"
    _touch_executable(binary)

    cli_file = tmp_path / "libexec" / "lib" / "python3.12" / "site-packages" / "whisper_local" / "cli.py"
    cli_file.parent.mkdir(parents=True, exist_ok=True)
    cli_file.touch()

    runtime = tui_runtime.resolve_tui_runtime(
        env={},
        sys_executable=str(python_bin),
        cli_file=cli_file,
        current_dir=tmp_path,
    )

    assert runtime.mode == "packaged"
    assert runtime.command == [str(binary)]


def test_resolve_runtime_dev_mode_searches_cli_parents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that dev mode searches for tui/ in CLI file parent directories."""
    repo_root = tmp_path / "repo"
    (repo_root / "tui" / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tui" / "src" / "index.tsx").write_text("export {};\n", encoding="utf-8")

    cli_file = repo_root / "src" / "whisper_local" / "cli.py"
    cli_file.parent.mkdir(parents=True, exist_ok=True)
    cli_file.touch()

    monkeypatch.setattr(tui_runtime.shutil, "which", lambda _: "/usr/local/bin/bun")

    runtime = tui_runtime.resolve_tui_runtime(
        env={tui_runtime.ENV_DEV_USE_BUN: "1"},
        sys_executable=str(tmp_path / "python"),
        cli_file=cli_file,
        current_dir=tmp_path,  # Different from repo_root
    )

    assert runtime.mode == "dev-bun"
    assert runtime.cwd == repo_root / "tui"


def test_resolve_runtime_dev_mode_missing_tui_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that dev mode raises error when tui/ directory not found."""
    monkeypatch.setattr(tui_runtime.shutil, "which", lambda _: "/usr/local/bin/bun")

    with pytest.raises(FileNotFoundError, match="local TUI source was not found"):
        tui_runtime.resolve_tui_runtime(
            env={tui_runtime.ENV_DEV_USE_BUN: "1"},
            sys_executable=str(tmp_path / "python"),
            cli_file=tmp_path / "src" / "whisper_local" / "cli.py",
            current_dir=tmp_path,
        )


def test_is_executable_file_not_executable(tmp_path: Path) -> None:
    """Test _is_executable_file returns False for non-executable file."""
    file = tmp_path / "not_executable.txt"
    file.write_text("test", encoding="utf-8")
    file.chmod(0o644)  # Not executable

    assert not tui_runtime._is_executable_file(file)


def test_is_executable_file_directory(tmp_path: Path) -> None:
    """Test _is_executable_file returns False for directory."""
    directory = tmp_path / "dir"
    directory.mkdir()

    assert not tui_runtime._is_executable_file(directory)


def test_is_executable_file_nonexistent(tmp_path: Path) -> None:
    """Test _is_executable_file returns False for nonexistent path."""
    nonexistent = tmp_path / "nonexistent"

    assert not tui_runtime._is_executable_file(nonexistent)


def test_packaged_tui_candidates_deduplicates(tmp_path: Path) -> None:
    """Test _packaged_tui_candidates removes duplicate paths."""
    sys_executable = tmp_path / "bin" / "python"
    cli_file = tmp_path / "bin" / "cli.py"

    candidates = tui_runtime._packaged_tui_candidates(
        sys_executable_path=sys_executable,
        cli_file_path=cli_file,
    )

    # Check no duplicates
    assert len(candidates) == len(set(candidates))


def test_find_local_tui_directory_not_found(tmp_path: Path) -> None:
    """Test _find_local_tui_directory returns None when tui/ not found."""
    cli_file = tmp_path / "src" / "whisper_local" / "cli.py"
    cli_file.parent.mkdir(parents=True)
    cli_file.touch()

    result = tui_runtime._find_local_tui_directory(
        cli_file_path=cli_file,
        current_dir=tmp_path,
    )

    assert result is None


def test_find_local_tui_directory_in_current_dir(tmp_path: Path) -> None:
    """Test _find_local_tui_directory finds tui/ in current directory."""
    tui_dir = tmp_path / "tui" / "src"
    tui_dir.mkdir(parents=True)
    (tui_dir / "index.tsx").write_text("export {};\n", encoding="utf-8")

    cli_file = tmp_path / "other" / "cli.py"
    cli_file.parent.mkdir(parents=True)
    cli_file.touch()

    result = tui_runtime._find_local_tui_directory(
        cli_file_path=cli_file,
        current_dir=tmp_path,
    )

    assert result == tmp_path / "tui"


def test_tui_runtime_dataclass():
    """Test TuiRuntime dataclass creation."""
    runtime = tui_runtime.TuiRuntime(
        mode="test-mode",
        command=["test", "command"],
        cwd=Path("/test/cwd")
    )

    assert runtime.mode == "test-mode"
    assert runtime.command == ["test", "command"]
    assert runtime.cwd == Path("/test/cwd")


def test_tui_runtime_frozen():
    """Test TuiRuntime is frozen (immutable)."""
    runtime = tui_runtime.TuiRuntime(
        mode="test-mode",
        command=["test"],
        cwd=None
    )

    with pytest.raises(AttributeError):
        runtime.mode = "different-mode"


def test_resolve_runtime_with_tilde_in_env_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test resolve_tui_runtime expands ~ in ENV_TUI_BIN path."""
    # Create a binary in a location that will be resolved
    home_dir = tmp_path / "home"
    binary = home_dir / "bin" / "whisper-local-tui"
    _touch_executable(binary)

    monkeypatch.setenv("HOME", str(home_dir))

    runtime = tui_runtime.resolve_tui_runtime(
        env={tui_runtime.ENV_TUI_BIN: "~/bin/whisper-local-tui"},
        sys_executable=str(tmp_path / "python"),
        cli_file=tmp_path / "cli.py",
        current_dir=tmp_path,
    )

    assert runtime.mode == "env-override"
    assert runtime.command == [str(binary)]


def test_constants_defined():
    """Test that tui_runtime constants are defined."""
    assert hasattr(tui_runtime, 'ENV_TUI_BIN')
    assert hasattr(tui_runtime, 'ENV_DEV_USE_BUN')
    assert hasattr(tui_runtime, 'TUI_EXECUTABLE')
    assert tui_runtime.TUI_EXECUTABLE == "whisper-local-tui"
