from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from whisper_local import __version__
from whisper_local.service_manager import ServiceManager


DEFAULT_REPOSITORY = os.environ.get("WHISPER_LOCAL_REPO", "mjmammoth/whisper.local")
INSTALLER_HOME = Path("~/.local/share/whisper.local").expanduser()
INSTALLER_MANIFEST_NAME = "install-manifest.json"
INSTALLER_MANIFEST = INSTALLER_HOME / INSTALLER_MANIFEST_NAME


class UpgradeError(RuntimeError):
    pass


class UpgradeActionRequired(UpgradeError):
    def __init__(self, *, channel: str, command: str) -> None:
        self.channel = channel
        self.command = command
        super().__init__(
            f"Automatic upgrade is unavailable for '{channel}' installs. Run: {command}"
        )


@dataclass(frozen=True)
class ReleaseAssetBundle:
    repository: str
    tag: str
    wheel_name: str
    wheel_url: str
    tui_name: str
    tui_url: str
    target: str


@dataclass(frozen=True)
class UpgradeResult:
    channel: str
    tag: str
    previous_version: str
    new_version: str
    restarted_service: bool


def detect_target() -> str:
    machine = (os.uname().machine if hasattr(os, "uname") else "").lower() or os.environ.get(
        "PROCESSOR_ARCHITECTURE", ""
    ).lower()

    if sys.platform == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "darwin-arm64"
        if machine in {"x86_64", "amd64"}:
            return "darwin-x64"

    if sys.platform.startswith("linux"):
        if machine in {"x86_64", "amd64"}:
            return "linux-x64"
        if machine in {"aarch64", "arm64"}:
            return "linux-arm64"

    if sys.platform in {"win32", "cygwin", "msys"}:
        if machine in {"x86_64", "amd64", "amd64t", "x64"}:
            return "windows-x64"

    raise UpgradeError(f"Unsupported platform/architecture for upgrade: {sys.platform}/{machine}")


def detect_install_channel(
    *,
    executable: str | None = None,
    installer_home: Path = INSTALLER_HOME,
) -> str:
    current_executable = Path(executable or sys.executable).expanduser().resolve()
    manifest = read_install_manifest(installer_home / INSTALLER_MANIFEST_NAME)
    if _manifest_indicates_installer(manifest, installer_home):
        return "installer"

    venv_root = installer_home / "venv"
    tui_root = installer_home / "tui"

    if tui_root.exists() and venv_root.exists():
        try:
            if current_executable.is_relative_to(venv_root):
                return "installer"
        except Exception:
            pass

    if _looks_like_homebrew_install(current_executable):
        return "homebrew"

    return "pip"


def read_install_manifest(
    manifest_path: Path = INSTALLER_MANIFEST,
) -> dict[str, object] | None:
    try:
        if not manifest_path.exists():
            return None
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _manifest_indicates_installer(
    manifest: dict[str, object] | None,
    installer_home: Path,
) -> bool:
    if manifest is None:
        return False

    channel = str(manifest.get("channel") or "").strip().lower()
    if channel != "installer":
        return False

    manifest_home_raw = str(manifest.get("installer_home") or "").strip()
    if not manifest_home_raw:
        return False

    try:
        manifest_home = Path(manifest_home_raw).expanduser().resolve()
        expected_home = installer_home.expanduser().resolve()
    except Exception:
        return False

    if manifest_home != expected_home:
        return False

    return (expected_home / "venv").exists() and (expected_home / "tui").exists()


def _looks_like_homebrew_install(executable: Path) -> bool:
    executable_text = str(executable)
    if "Cellar/whisper-local" in executable_text:
        return True

    brew_bin = shutil.which("brew")
    if not brew_bin:
        return False

    try:
        result = subprocess.run(
            [brew_bin, "--prefix", "whisper-local"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False

    prefix = result.stdout.strip()
    if not prefix:
        return False

    try:
        resolved_executable = executable.expanduser().resolve()
        resolved_prefix = Path(prefix).expanduser().resolve()
    except Exception:
        return False

    try:
        return resolved_executable.is_relative_to(resolved_prefix)
    except Exception:
        resolved_executable_text = str(resolved_executable)
        resolved_prefix_text = str(resolved_prefix)
        prefix_with_sep = f"{resolved_prefix_text}{os.sep}"
        return resolved_executable_text == resolved_prefix_text or resolved_executable_text.startswith(
            prefix_with_sep
        )


def normalize_version_tag(requested_version: str | None) -> str | None:
    if requested_version is None:
        return None
    normalized = requested_version.strip()
    if not normalized:
        return None
    if normalized == "latest":
        return None
    if normalized.startswith("v"):
        return normalized
    return f"v{normalized}"


def _github_get_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "whisper-local-upgrade",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw_payload = response.read().decode("utf-8")
    return json.loads(raw_payload)


def resolve_release_assets(
    *,
    repository: str = DEFAULT_REPOSITORY,
    requested_version: str | None = None,
    target: str | None = None,
) -> ReleaseAssetBundle:
    normalized_tag = normalize_version_tag(requested_version)
    target_name = target or detect_target()

    if normalized_tag is None:
        url = f"https://api.github.com/repos/{repository}/releases/latest"
    else:
        encoded_tag = urllib.parse.quote(normalized_tag, safe="")
        url = f"https://api.github.com/repos/{repository}/releases/tags/{encoded_tag}"

    try:
        payload = _github_get_json(url)
    except Exception as exc:
        raise UpgradeError(f"Failed to fetch release metadata: {exc}") from exc

    tag = str(payload.get("tag_name") or normalized_tag or "")
    if not tag:
        raise UpgradeError("Release metadata did not include a valid tag")

    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        raise UpgradeError("Release metadata has invalid assets payload")

    wheel_assets: list[dict[str, object]] = []
    tui_asset = None
    expected_tui = f"whisper-local-tui-{target_name}.tar.gz"
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_name = str(asset.get("name") or "")
        if asset_name.endswith(".whl"):
            wheel_assets.append(asset)
        if asset_name == expected_tui:
            tui_asset = asset

    if not wheel_assets:
        raise UpgradeError("Release is missing wheel artifact")
    if len(wheel_assets) > 1:
        wheel_names = ", ".join(sorted(str(asset.get("name") or "") for asset in wheel_assets))
        raise UpgradeError(
            f"Release contains multiple wheel artifacts; unable to select automatically: {wheel_names}"
        )
    if tui_asset is None:
        raise UpgradeError(f"Release is missing TUI artifact for target {target_name}")

    wheel_asset = wheel_assets[0]
    wheel_name = str(wheel_asset.get("name") or "")
    wheel_url = str(wheel_asset.get("browser_download_url") or "")
    tui_name = str(tui_asset.get("name") or "")
    tui_url = str(tui_asset.get("browser_download_url") or "")

    if not wheel_url or not tui_url:
        raise UpgradeError("Release assets are missing download URLs")

    return ReleaseAssetBundle(
        repository=repository,
        tag=tag,
        wheel_name=wheel_name,
        wheel_url=wheel_url,
        tui_name=tui_name,
        tui_url=tui_url,
        target=target_name,
    )


def _download_to_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "whisper-local-upgrade",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def _replace_tui_binary(*, app_home: Path, target: str, archive_path: Path) -> None:
    target_dir = app_home / "tui" / target
    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="whisper-local-upgrade-tui-") as tmp_dir:
        extract_root = Path(tmp_dir)
        with tarfile.open(archive_path, "r:gz") as tar_handle:
            tar_handle.extractall(extract_root, filter="data")

        candidates = [
            extract_root / "whisper-local-tui",
            extract_root / "whisper-local-tui.exe",
        ]
        extracted_binary = next((candidate for candidate in candidates if candidate.exists()), None)
        if extracted_binary is None:
            raise UpgradeError("Upgraded TUI archive did not contain an executable")

        destination = target_dir / extracted_binary.name
        staged_destination = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(extracted_binary, staged_destination)
        os.replace(staged_destination, destination)
        if not destination.name.endswith(".exe"):
            destination.chmod(0o755)


def _installed_version(python_executable: str) -> str:
    try:
        result = subprocess.run(
            [
                python_executable,
                "-c",
                "import whisper_local; print(whisper_local.__version__)",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        parsed = result.stdout.strip()
        return parsed or __version__
    except Exception:
        return __version__


def _guidance_command_for_channel(channel: str) -> str:
    if channel == "homebrew":
        return "brew update && brew upgrade whisper-local"
    return "python -m pip install -U whisper-local"


def run_upgrade(
    *,
    requested_version: str | None = None,
    repository: str = DEFAULT_REPOSITORY,
    installer_home: Path = INSTALLER_HOME,
    service_manager: ServiceManager | None = None,
) -> UpgradeResult:
    channel = detect_install_channel(installer_home=installer_home)
    if channel != "installer":
        raise UpgradeActionRequired(channel=channel, command=_guidance_command_for_channel(channel))

    manager = service_manager or ServiceManager()
    status_before = manager.status()
    was_running = bool(status_before.running)
    host = status_before.host or "localhost"
    port = int(status_before.port or 7878)
    status_indicator = bool(status_before.status_indicator_pid is not None or sys.platform == "darwin")

    previous_version = _installed_version(sys.executable)
    if was_running:
        manager.stop()

    try:
        assets = resolve_release_assets(
            repository=repository,
            requested_version=requested_version,
        )

        with tempfile.TemporaryDirectory(prefix="whisper-local-upgrade-") as tmp_dir:
            tmp_root = Path(tmp_dir)
            wheel_path = tmp_root / assets.wheel_name
            tui_path = tmp_root / assets.tui_name

            _download_to_file(assets.wheel_url, wheel_path)
            _download_to_file(assets.tui_url, tui_path)

            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", str(wheel_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _replace_tui_binary(
                app_home=installer_home,
                target=assets.target,
                archive_path=tui_path,
            )

        restarted_service = False
        if was_running:
            manager.start_background(host=host, port=port, status_indicator=status_indicator)
            restarted_service = True

        new_version = _installed_version(sys.executable)
        return UpgradeResult(
            channel=channel,
            tag=assets.tag,
            previous_version=previous_version,
            new_version=new_version,
            restarted_service=restarted_service,
        )
    except Exception as exc:
        if was_running:
            try:
                manager.start_background(host=host, port=port, status_indicator=status_indicator)
            except Exception:
                pass
        if isinstance(exc, UpgradeError):
            raise
        raise UpgradeError(f"Upgrade failed: {exc}") from exc
