from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from whisper_local.config import default_config_path
from whisper_local.model_manager import whisper_local_model_cache_paths
from whisper_local.service_manager import ServiceManager
from whisper_local.service_state import state_directory
from whisper_local.upgrade import (
    INSTALLER_HOME,
    INSTALLER_MANIFEST_NAME,
    detect_install_channel,
    read_install_manifest,
)


DEFAULT_LAUNCHER_PATH = Path("~/.local/bin/murmur").expanduser()


class UninstallError(RuntimeError):
    pass


class UninstallActionRequired(UninstallError):
    def __init__(self, *, channel: str, command: str) -> None:
        self.channel = channel
        self.command = command
        super().__init__(
            f"Automatic uninstall is unavailable for '{channel}' installs. Run: {command}"
        )


@dataclass(frozen=True)
class UninstallOptions:
    remove_state: bool = False
    remove_config: bool = False
    remove_model_cache: bool = False


@dataclass(frozen=True)
class RemovalFailure:
    path: Path
    reason: str


@dataclass(frozen=True)
class UninstallResult:
    channel: str
    removed_paths: tuple[Path, ...]
    failed_paths: tuple[RemovalFailure, ...]
    warnings: tuple[str, ...]


def run_uninstall(
    *,
    options: UninstallOptions,
    installer_home: Path = INSTALLER_HOME,
    service_manager: ServiceManager | None = None,
    executable: str | None = None,
) -> UninstallResult:
    channel = detect_install_channel(executable=executable, installer_home=installer_home)
    if channel != "installer":
        raise UninstallActionRequired(
            channel=channel,
            command=_guidance_command_for_channel(channel),
        )

    try:
        return _run_installer_uninstall(
            options=options,
            installer_home=installer_home,
            service_manager=service_manager,
        )
    except UninstallActionRequired:
        raise
    except UninstallError:
        raise
    except Exception as exc:
        raise UninstallError(f"Uninstall failed: {exc}") from exc


def _run_installer_uninstall(
    *,
    options: UninstallOptions,
    installer_home: Path,
    service_manager: ServiceManager | None,
) -> UninstallResult:
    removed_paths: list[Path] = []
    failed_paths: list[RemovalFailure] = []
    warnings: list[str] = []

    manager = service_manager or ServiceManager()
    try:
        manager.stop()
    except Exception as exc:
        warnings.append(f"Failed to stop service cleanly: {exc}")

    for launcher_path in _installer_launcher_candidates(installer_home):
        if not _path_exists_or_symlink(launcher_path):
            continue
        if not _looks_like_installer_launcher(launcher_path, installer_home):
            warnings.append(f"Skipped non-installer launcher: {launcher_path}")
            continue
        _remove_path(launcher_path, removed_paths=removed_paths, failed_paths=failed_paths)

    _remove_path(installer_home, removed_paths=removed_paths, failed_paths=failed_paths)

    if options.remove_state:
        _remove_path(state_directory(), removed_paths=removed_paths, failed_paths=failed_paths)

    if options.remove_config:
        _remove_path(default_config_path().parent, removed_paths=removed_paths, failed_paths=failed_paths)

    if options.remove_model_cache:
        try:
            cache_paths = whisper_local_model_cache_paths()
        except Exception as exc:
            warnings.append(f"Failed to resolve model cache paths: {exc}")
            cache_paths = ()
        for cache_path in cache_paths:
            _remove_path(cache_path, removed_paths=removed_paths, failed_paths=failed_paths)

    return UninstallResult(
        channel="installer",
        removed_paths=tuple(removed_paths),
        failed_paths=tuple(failed_paths),
        warnings=tuple(warnings),
    )


def _remove_path(
    path: Path,
    *,
    removed_paths: list[Path],
    failed_paths: list[RemovalFailure],
) -> None:
    if not _path_exists_or_symlink(path):
        return
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
    except Exception as exc:
        failed_paths.append(RemovalFailure(path=path, reason=str(exc)))
        return
    removed_paths.append(path)


def _path_exists_or_symlink(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _installer_launcher_candidates(installer_home: Path) -> tuple[Path, ...]:
    manifest = read_install_manifest(installer_home / INSTALLER_MANIFEST_NAME)
    candidates = [
        DEFAULT_LAUNCHER_PATH.expanduser().resolve(strict=False),
    ]
    manifest_launchers = manifest.get("launchers") if manifest is not None else None
    if isinstance(manifest_launchers, list):
        for entry in manifest_launchers:
            if isinstance(entry, str) and entry.strip():
                candidates.append(Path(entry).expanduser().resolve(strict=False))

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return tuple(deduped)


def _looks_like_installer_launcher(path: Path, installer_home: Path) -> bool:
    if path.is_symlink():
        try:
            symlink_target = path.resolve(strict=False)
        except Exception:
            return False
        if _path_is_within(symlink_target, installer_home):
            return True
        if symlink_target == DEFAULT_LAUNCHER_PATH:
            return True

    if not path.is_file():
        return False

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    if str(installer_home) in content and "whisper_local.cli" in content:
        return True
    if (
        "MURMUR_TUI_BIN" in content
        and 'exec "${PYTHON_BIN}" -m whisper_local.cli "$@"' in content
        and "APP_HOME=" in content
    ):
        return True
    if (
        'exec "${SCRIPT_DIR}/murmur" "$@"' in content
        and "SCRIPT_DIR=" in content
        and "set -euo pipefail" in content
    ):
        return True

    return False


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        return path.expanduser().resolve().is_relative_to(root.expanduser().resolve())
    except Exception:
        try:
            resolved_path = str(path.expanduser().resolve())
            resolved_root = str(root.expanduser().resolve())
        except Exception:
            return False
        return resolved_path == resolved_root or resolved_path.startswith(f"{resolved_root}{os.sep}")


def _guidance_command_for_channel(channel: str) -> str:
    if channel == "homebrew":
        return "brew uninstall murmur"
    return "python -m pip uninstall murmur"
