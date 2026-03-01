from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_local import uninstall
from whisper_local.upgrade import INSTALLER_MANIFEST_NAME


def _write_manifest(installer_home: Path, launchers: list[Path]) -> None:
    manifest_path = installer_home / INSTALLER_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "channel": "installer",
                "installer_home": str(installer_home),
                "launchers": [str(path) for path in launchers],
            }
        ),
        encoding="utf-8",
    )


def _write_primary_launcher(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
APP_HOME="${MURMUR_HOME:-${HOME}/.local/share/murmur}"
export MURMUR_TUI_BIN="${APP_HOME}/tui/linux-x64/murmur-tui"
exec "${PYTHON_BIN}" -m whisper_local.cli "$@"
""",
        encoding="utf-8",
    )


def _write_alt_launcher(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/murmur" "$@"
""",
        encoding="utf-8",
    )


def _prepare_installer_layout(tmp_path: Path) -> tuple[Path, Path]:
    installer_home = tmp_path / "installer-home"
    python_exe = installer_home / "venv" / "bin" / "python"
    python_exe.parent.mkdir(parents=True, exist_ok=True)
    python_exe.write_text("", encoding="utf-8")
    (installer_home / "tui").mkdir(parents=True, exist_ok=True)
    return installer_home, python_exe


def test_run_uninstall_installer_app_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installer_home, python_exe = _prepare_installer_layout(tmp_path)
    primary_launcher = tmp_path / "bin" / "murmur"
    alt_launcher = tmp_path / "bin" / "murmur-link"
    _write_primary_launcher(primary_launcher)
    _write_alt_launcher(alt_launcher)
    _write_manifest(installer_home, [primary_launcher, alt_launcher])

    monkeypatch.setattr(uninstall, "DEFAULT_LAUNCHER_PATH", primary_launcher)
    monkeypatch.setattr(uninstall, "ALT_LAUNCHER_PATH", alt_launcher)

    manager = Mock()
    result = uninstall.run_uninstall(
        options=uninstall.UninstallOptions(),
        installer_home=installer_home,
        service_manager=manager,
        executable=str(python_exe),
    )

    manager.stop.assert_called_once()
    assert not installer_home.exists()
    assert not primary_launcher.exists()
    assert not alt_launcher.exists()
    assert result.channel == "installer"
    assert not result.failed_paths


def test_run_uninstall_installer_with_all_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installer_home, python_exe = _prepare_installer_layout(tmp_path)
    primary_launcher = tmp_path / "bin" / "murmur"
    alt_launcher = tmp_path / "bin" / "murmur-link"
    _write_primary_launcher(primary_launcher)
    _write_alt_launcher(alt_launcher)
    _write_manifest(installer_home, [primary_launcher, alt_launcher])

    state_dir = tmp_path / "state" / "murmur"
    config_dir = tmp_path / "config" / "murmur"
    cache_a = tmp_path / "hf" / "hub" / "models--repo-a"
    cache_b = tmp_path / "hf" / "hub" / "models--repo-b"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    cache_a.mkdir(parents=True, exist_ok=True)
    cache_b.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(uninstall, "DEFAULT_LAUNCHER_PATH", primary_launcher)
    monkeypatch.setattr(uninstall, "ALT_LAUNCHER_PATH", alt_launcher)
    monkeypatch.setattr(uninstall, "state_directory", lambda: state_dir)
    monkeypatch.setattr(uninstall, "default_config_path", lambda: config_dir / "config.toml")
    monkeypatch.setattr(uninstall, "whisper_local_model_cache_paths", lambda: (cache_a, cache_b))

    result = uninstall.run_uninstall(
        options=uninstall.UninstallOptions(
            remove_state=True,
            remove_config=True,
            remove_model_cache=True,
        ),
        installer_home=installer_home,
        service_manager=Mock(),
        executable=str(python_exe),
    )

    assert not state_dir.exists()
    assert not config_dir.exists()
    assert not cache_a.exists()
    assert not cache_b.exists()
    assert not result.failed_paths


def test_run_uninstall_non_installer_returns_guidance(tmp_path: Path) -> None:
    with patch("whisper_local.uninstall.detect_install_channel", return_value="homebrew"):
        with pytest.raises(uninstall.UninstallActionRequired) as exc_info:
            uninstall.run_uninstall(
                options=uninstall.UninstallOptions(),
                installer_home=tmp_path,
            )

    assert exc_info.value.channel == "homebrew"
    assert "brew uninstall murmur" in exc_info.value.command


def test_run_uninstall_pip_channel_returns_guidance(tmp_path: Path) -> None:
    with patch("whisper_local.uninstall.detect_install_channel", return_value="pip"):
        with pytest.raises(uninstall.UninstallActionRequired) as exc_info:
            uninstall.run_uninstall(
                options=uninstall.UninstallOptions(),
                installer_home=tmp_path,
            )

    assert exc_info.value.channel == "pip"
    assert "python -m pip uninstall murmur" in exc_info.value.command


def test_run_uninstall_skips_unknown_launchers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installer_home, python_exe = _prepare_installer_layout(tmp_path)
    unknown_launcher = tmp_path / "bin" / "murmur"
    unknown_launcher.parent.mkdir(parents=True, exist_ok=True)
    unknown_launcher.write_text("#!/usr/bin/env bash\necho custom\n", encoding="utf-8")
    _write_manifest(installer_home, [unknown_launcher])

    monkeypatch.setattr(uninstall, "DEFAULT_LAUNCHER_PATH", unknown_launcher)
    monkeypatch.setattr(uninstall, "ALT_LAUNCHER_PATH", tmp_path / "bin" / "murmur-link")

    result = uninstall.run_uninstall(
        options=uninstall.UninstallOptions(),
        installer_home=installer_home,
        service_manager=Mock(),
        executable=str(python_exe),
    )

    assert unknown_launcher.exists()
    assert any("Skipped non-installer launcher" in warning for warning in result.warnings)


def test_run_uninstall_collects_removal_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installer_home, python_exe = _prepare_installer_layout(tmp_path)
    primary_launcher = tmp_path / "bin" / "murmur"
    _write_primary_launcher(primary_launcher)
    _write_manifest(installer_home, [primary_launcher])

    monkeypatch.setattr(uninstall, "DEFAULT_LAUNCHER_PATH", primary_launcher)
    monkeypatch.setattr(uninstall, "ALT_LAUNCHER_PATH", tmp_path / "bin" / "murmur-link")

    original_remove_path = uninstall._remove_path

    def _failing_remove(
        path: Path,
        *,
        removed_paths: list[Path],
        failed_paths: list[uninstall.RemovalFailure],
    ) -> None:
        if path == installer_home:
            failed_paths.append(uninstall.RemovalFailure(path=path, reason="simulated failure"))
            return
        original_remove_path(path, removed_paths=removed_paths, failed_paths=failed_paths)

    monkeypatch.setattr(uninstall, "_remove_path", _failing_remove)

    result = uninstall.run_uninstall(
        options=uninstall.UninstallOptions(),
        installer_home=installer_home,
        service_manager=Mock(),
        executable=str(python_exe),
    )

    assert result.failed_paths
    assert result.failed_paths[0].path == installer_home


# ---------------------------------------------------------------------------
# _remove_path edge cases
# ---------------------------------------------------------------------------

def test_remove_path_file(tmp_path: Path) -> None:
    f = tmp_path / "testfile"
    f.write_text("hello")
    removed: list[Path] = []
    failed: list[uninstall.RemovalFailure] = []
    uninstall._remove_path(f, removed_paths=removed, failed_paths=failed)
    assert f in removed
    assert not f.exists()


def test_remove_path_directory(tmp_path: Path) -> None:
    d = tmp_path / "testdir"
    d.mkdir()
    (d / "child").write_text("x")
    removed: list[Path] = []
    failed: list[uninstall.RemovalFailure] = []
    uninstall._remove_path(d, removed_paths=removed, failed_paths=failed)
    assert d in removed


def test_remove_path_nonexistent(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    removed: list[Path] = []
    failed: list[uninstall.RemovalFailure] = []
    uninstall._remove_path(missing, removed_paths=removed, failed_paths=failed)
    assert len(removed) == 0
    assert len(failed) == 0


def test_remove_path_failure(tmp_path: Path) -> None:
    f = tmp_path / "testfile"
    f.write_text("hello")
    removed: list[Path] = []
    failed: list[uninstall.RemovalFailure] = []
    with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
        uninstall._remove_path(f, removed_paths=removed, failed_paths=failed)
    assert len(failed) == 1
    assert failed[0].path == f


# ---------------------------------------------------------------------------
# _looks_like_installer_launcher
# ---------------------------------------------------------------------------

def test_looks_like_installer_launcher_symlink(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    installer_home.mkdir()
    target = installer_home / "bin" / "murmur"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/bash")
    link = tmp_path / "launcher"
    link.symlink_to(target)
    assert uninstall._looks_like_installer_launcher(link, installer_home) is True


def test_looks_like_installer_launcher_script_content(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    installer_home.mkdir()
    script = tmp_path / "launcher"
    script.write_text(f"#!/bin/bash\n{installer_home}/venv/bin/python -m whisper_local.cli \"$@\"")
    assert uninstall._looks_like_installer_launcher(script, installer_home) is True


def test_looks_like_installer_launcher_not_file(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    installer_home.mkdir()
    d = tmp_path / "notfile"
    d.mkdir()
    assert uninstall._looks_like_installer_launcher(d, installer_home) is False


# ---------------------------------------------------------------------------
# _path_is_within
# ---------------------------------------------------------------------------

def test_path_is_within_true(tmp_path: Path) -> None:
    child = tmp_path / "a" / "b"
    assert uninstall._path_is_within(child, tmp_path) is True


def test_path_is_within_false(tmp_path: Path) -> None:
    other = Path("/some/other/path")
    assert uninstall._path_is_within(other, tmp_path) is False


# ---------------------------------------------------------------------------
# _guidance_command_for_channel
# ---------------------------------------------------------------------------

def test_guidance_command_homebrew() -> None:
    assert "brew" in uninstall._guidance_command_for_channel("homebrew")


def test_guidance_command_pip() -> None:
    assert "pip" in uninstall._guidance_command_for_channel("pip")


# ---------------------------------------------------------------------------
# _path_exists_or_symlink
# ---------------------------------------------------------------------------

def test_path_exists_or_symlink_exists(tmp_path: Path) -> None:
    f = tmp_path / "exists"
    f.write_text("hi")
    assert uninstall._path_exists_or_symlink(f) is True


def test_path_exists_or_symlink_missing(tmp_path: Path) -> None:
    assert uninstall._path_exists_or_symlink(tmp_path / "missing") is False


def test_path_exists_or_symlink_broken_symlink(tmp_path: Path) -> None:
    link = tmp_path / "broken_link"
    link.symlink_to(tmp_path / "nonexistent_target")
    assert uninstall._path_exists_or_symlink(link) is True


# ---------------------------------------------------------------------------
# run_uninstall — exception wrapping
# ---------------------------------------------------------------------------

def test_run_uninstall_wraps_unexpected_exception(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    venv_dir = installer_home / "venv" / "bin"
    venv_dir.mkdir(parents=True)
    python_exe = venv_dir / "python"
    python_exe.write_text("#!/usr/bin/env python", encoding="utf-8")

    _write_manifest(installer_home, [])

    with patch(
        "whisper_local.uninstall._run_installer_uninstall",
        side_effect=RuntimeError("unexpected"),
    ):
        with pytest.raises(uninstall.UninstallError, match="Uninstall failed"):
            uninstall.run_uninstall(
                options=uninstall.UninstallOptions(),
                installer_home=installer_home,
                executable=str(python_exe),
            )


# ---------------------------------------------------------------------------
# _run_installer_uninstall — service stop failure
# ---------------------------------------------------------------------------

def test_run_installer_uninstall_service_stop_failure(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    installer_home.mkdir()

    manager = Mock()
    manager.stop.side_effect = RuntimeError("stop failed")

    result = uninstall._run_installer_uninstall(
        options=uninstall.UninstallOptions(),
        installer_home=installer_home,
        service_manager=manager,
    )
    assert any("Failed to stop" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# _run_installer_uninstall — model cache resolution error
# ---------------------------------------------------------------------------

def test_run_installer_uninstall_model_cache_error(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    installer_home.mkdir()

    with patch("whisper_local.uninstall.whisper_local_model_cache_paths", side_effect=Exception("fail")):
        result = uninstall._run_installer_uninstall(
            options=uninstall.UninstallOptions(remove_model_cache=True),
            installer_home=installer_home,
            service_manager=Mock(),
        )
    assert any("Failed to resolve model cache" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# _looks_like_installer_launcher — read error
# ---------------------------------------------------------------------------

def test_looks_like_installer_launcher_read_error(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    installer_home.mkdir()
    f = tmp_path / "launcher"
    f.write_text("content")
    with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
        assert uninstall._looks_like_installer_launcher(f, installer_home) is False


def test_run_uninstall_propagates_action_required(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    venv_dir = installer_home / "venv" / "bin"
    venv_dir.mkdir(parents=True)
    python_exe = venv_dir / "python"
    python_exe.write_text("#!/usr/bin/env python", encoding="utf-8")

    _write_manifest(installer_home, [])

    with patch(
        "whisper_local.uninstall._run_installer_uninstall",
        side_effect=uninstall.UninstallActionRequired(channel="homebrew", command="brew uninstall"),
    ):
        with pytest.raises(uninstall.UninstallActionRequired):
            uninstall.run_uninstall(
                options=uninstall.UninstallOptions(),
                installer_home=installer_home,
                executable=str(python_exe),
            )


def test_run_uninstall_propagates_uninstall_error(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    venv_dir = installer_home / "venv" / "bin"
    venv_dir.mkdir(parents=True)
    python_exe = venv_dir / "python"
    python_exe.write_text("#!/usr/bin/env python", encoding="utf-8")

    _write_manifest(installer_home, [])

    with patch(
        "whisper_local.uninstall._run_installer_uninstall",
        side_effect=uninstall.UninstallError("specific error"),
    ):
        with pytest.raises(uninstall.UninstallError, match="specific error"):
            uninstall.run_uninstall(
                options=uninstall.UninstallOptions(),
                installer_home=installer_home,
                executable=str(python_exe),
            )


# ---------------------------------------------------------------------------
# _looks_like_installer_launcher — symlink resolve exception
# ---------------------------------------------------------------------------

def test_looks_like_installer_launcher_symlink_resolve_error(tmp_path: Path) -> None:
    installer_home = tmp_path / "murmur"
    installer_home.mkdir()
    link = tmp_path / "link"
    target = installer_home / "bin" / "murmur"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    link.symlink_to(target)

    with patch.object(Path, "resolve", side_effect=OSError("resolve failed")):
        assert uninstall._looks_like_installer_launcher(link, installer_home) is False
