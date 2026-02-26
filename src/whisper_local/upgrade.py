from __future__ import annotations

import hashlib
import json
import os
import re
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
DEFAULT_EXPECTED_SIGNING_FINGERPRINT = "031A071DD2F8736D5AB270EF239D1750F8F92826"
INSTALLER_HOME = Path("~/.local/share/whisper.local").expanduser()
INSTALLER_MANIFEST_NAME = "install-manifest.json"
INSTALLER_MANIFEST = INSTALLER_HOME / INSTALLER_MANIFEST_NAME
CHECKSUM_MANIFEST_NAMES = {"checksums.txt", "checksums.sha256", "checksums.sha256sum"}


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
    checksums_name: str
    checksums_url: str
    signature_name: str
    signature_url: str
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
    venv_root = installer_home / "venv"

    if venv_root.exists():
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


def _normalize_fingerprint(value: str) -> str:
    return "".join(value.split()).upper()


def _expected_signing_fingerprint() -> str:
    configured = os.environ.get(
        "WHISPER_LOCAL_SIGNING_KEY_FINGERPRINT",
        DEFAULT_EXPECTED_SIGNING_FINGERPRINT,
    )
    fingerprint = _normalize_fingerprint(configured)
    if not fingerprint:
        raise UpgradeError(
            "Upgrade verification failed: signing key fingerprint is empty "
            "(set WHISPER_LOCAL_SIGNING_KEY_FINGERPRINT)."
        )
    return fingerprint


def _signing_key_url_for_repository(repository: str) -> str:
    override = os.environ.get("WHISPER_LOCAL_SIGNING_KEY_URL")
    if override and override.strip():
        return override.strip()

    owner = repository.split("/", 1)[0].strip()
    if not owner:
        raise UpgradeError(
            f"Upgrade verification failed: invalid repository '{repository}' for signing-key lookup."
        )
    return f"https://github.com/{owner}.gpg"


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
    tui_asset: dict[str, object] | None = None
    checksums_asset: dict[str, object] | None = None
    signature_asset: dict[str, object] | None = None
    expected_tui = f"whisper-local-tui-{target_name}.tar.gz"
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_name = str(asset.get("name") or "")
        if asset_name.endswith(".whl"):
            wheel_assets.append(asset)
        if asset_name == expected_tui:
            tui_asset = asset
        if asset_name in CHECKSUM_MANIFEST_NAMES:
            checksums_asset = asset

    if not wheel_assets:
        raise UpgradeError("Release is missing wheel artifact")
    if len(wheel_assets) > 1:
        wheel_names = ", ".join(sorted(str(asset.get("name") or "") for asset in wheel_assets))
        raise UpgradeError(
            f"Release contains multiple wheel artifacts; unable to select automatically: {wheel_names}"
        )
    if tui_asset is None:
        raise UpgradeError(f"Release is missing TUI artifact for target {target_name}")
    if checksums_asset is None:
        raise UpgradeError(
            "Release is missing checksum manifest (checksums.txt/.sha256/.sha256sum)"
        )

    checksums_name = str(checksums_asset.get("name") or "")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_name = str(asset.get("name") or "")
        if asset_name in {f"{checksums_name}.asc", f"{checksums_name}.sig"}:
            signature_asset = asset
            break
    if signature_asset is None:
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_name = str(asset.get("name") or "").lower()
            if asset_name in {"release.asc", "release.sig"}:
                signature_asset = asset
                break
    if signature_asset is None:
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_name = str(asset.get("name") or "").lower()
            if asset_name.endswith(".asc") and "checksum" in asset_name:
                signature_asset = asset
                break
    if signature_asset is None:
        raise UpgradeError("Release is missing checksum signature (.asc/.sig)")

    wheel_asset = wheel_assets[0]
    wheel_name = str(wheel_asset.get("name") or "")
    wheel_url = str(wheel_asset.get("browser_download_url") or "")
    tui_name = str(tui_asset.get("name") or "")
    tui_url = str(tui_asset.get("browser_download_url") or "")
    checksums_url = str(checksums_asset.get("browser_download_url") or "")
    signature_name = str(signature_asset.get("name") or "")
    signature_url = str(signature_asset.get("browser_download_url") or "")

    if not wheel_url or not tui_url or not checksums_url or not signature_url:
        raise UpgradeError("Release assets are missing download URLs")

    return ReleaseAssetBundle(
        repository=repository,
        tag=tag,
        wheel_name=wheel_name,
        wheel_url=wheel_url,
        tui_name=tui_name,
        tui_url=tui_url,
        checksums_name=checksums_name,
        checksums_url=checksums_url,
        signature_name=signature_name,
        signature_url=signature_url,
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
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)


def _run_command_or_error(command: list[str], *, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except Exception as exc:
        joined = " ".join(command)
        raise UpgradeError(f"Upgrade verification failed while running '{joined}': {exc}") from exc

    if result.returncode != 0:
        joined = " ".join(command)
        stderr = result.stderr.strip() or result.stdout.strip()
        suffix = f": {stderr}" if stderr else ""
        raise UpgradeError(f"Upgrade verification failed while running '{joined}'{suffix}")
    return result.stdout


def _parse_checksums_manifest(manifest_path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    pattern = re.compile(r"^([0-9A-Fa-f]{64})\s+\*?(.+)$")
    for raw_line in manifest_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        digest = match.group(1).lower()
        name = match.group(2).strip()
        if name:
            entries[name] = digest
    if not entries:
        raise UpgradeError(
            f"Upgrade verification failed: checksum manifest is empty or invalid ({manifest_path.name})."
        )
    return entries


def _checksum_for_asset(asset_name: str, checksums: dict[str, str]) -> str:
    if asset_name in checksums:
        return checksums[asset_name]

    basename_matches = [
        digest for entry_name, digest in checksums.items() if Path(entry_name).name == asset_name
    ]
    if len(basename_matches) == 1:
        return basename_matches[0]
    if len(basename_matches) > 1:
        raise UpgradeError(
            f"Upgrade verification failed: multiple checksum entries matched asset '{asset_name}'."
        )
    raise UpgradeError(
        f"Upgrade verification failed: checksum entry missing for asset '{asset_name}'."
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _verify_release_signature(
    *,
    repository: str,
    checksums_path: Path,
    signature_path: Path,
) -> None:
    gpg = shutil.which("gpg")
    if not gpg:
        raise UpgradeError(
            "Upgrade verification failed: 'gpg' is required. Install gpg and re-run upgrade."
        )

    expected_fingerprint = _expected_signing_fingerprint()
    signing_key_url = _signing_key_url_for_repository(repository)

    with tempfile.TemporaryDirectory(prefix="whisper-local-upgrade-gpg-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        gpg_home = tmp_root / "gnupg"
        gpg_home.mkdir(parents=True, exist_ok=True)
        gpg_home.chmod(0o700)
        key_path = tmp_root / "release-signing-key.asc"
        try:
            _download_to_file(signing_key_url, key_path)
        except Exception as exc:
            raise UpgradeError(
                f"Upgrade verification failed: could not download signing key from {signing_key_url}: {exc}"
            ) from exc

        env = os.environ.copy()
        env["GNUPGHOME"] = str(gpg_home)

        _run_command_or_error(
            [gpg, "--batch", "--quiet", "--import", str(key_path)],
            env=env,
        )
        fingerprint_output = _run_command_or_error(
            [gpg, "--batch", "--with-colons", "--fingerprint"],
            env=env,
        )
        imported_fingerprints = {
            parts[9].strip().upper()
            for line in fingerprint_output.splitlines()
            if line.startswith("fpr:")
            for parts in [line.split(":")]
            if len(parts) > 9 and parts[9].strip()
        }
        if expected_fingerprint not in imported_fingerprints:
            raise UpgradeError(
                "Upgrade verification failed: expected signing key fingerprint was not found "
                "in imported keyring."
            )
        _run_command_or_error(
            [gpg, "--batch", "--quiet", "--verify", str(signature_path), str(checksums_path)],
            env=env,
        )


def _verify_downloaded_release_assets(
    *,
    bundle: ReleaseAssetBundle,
    checksums_path: Path,
    signature_path: Path,
    wheel_path: Path,
    tui_path: Path,
) -> None:
    _verify_release_signature(
        repository=bundle.repository,
        checksums_path=checksums_path,
        signature_path=signature_path,
    )
    checksums = _parse_checksums_manifest(checksums_path)

    expected_wheel_digest = _checksum_for_asset(bundle.wheel_name, checksums)
    expected_tui_digest = _checksum_for_asset(bundle.tui_name, checksums)
    actual_wheel_digest = _sha256_file(wheel_path)
    actual_tui_digest = _sha256_file(tui_path)

    if actual_wheel_digest.lower() != expected_wheel_digest.lower():
        raise UpgradeError(
            f"Upgrade verification failed: wheel checksum mismatch for {bundle.wheel_name}."
        )
    if actual_tui_digest.lower() != expected_tui_digest.lower():
        raise UpgradeError(
            f"Upgrade verification failed: TUI checksum mismatch for {bundle.tui_name}."
        )


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
            checksums_path = tmp_root / assets.checksums_name
            signature_path = tmp_root / assets.signature_name

            _download_to_file(assets.wheel_url, wheel_path)
            _download_to_file(assets.tui_url, tui_path)
            _download_to_file(assets.checksums_url, checksums_path)
            _download_to_file(assets.signature_url, signature_path)

            _verify_downloaded_release_assets(
                bundle=assets,
                checksums_path=checksums_path,
                signature_path=signature_path,
                wheel_path=wheel_path,
                tui_path=tui_path,
            )

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
        restart_exc: Exception | None = None
        if was_running:
            try:
                manager.start_background(host=host, port=port, status_indicator=status_indicator)
            except Exception as restart_error:
                restart_exc = restart_error
        if restart_exc is not None:
            if isinstance(exc, UpgradeError):
                raise UpgradeError(
                    f"{exc}; additionally failed to restart service: {restart_exc}"
                ) from exc
            raise UpgradeError(
                f"Upgrade failed: {exc}; additionally failed to restart service: {restart_exc}"
            ) from exc
        if isinstance(exc, UpgradeError):
            raise
        raise UpgradeError(f"Upgrade failed: {exc}") from exc
