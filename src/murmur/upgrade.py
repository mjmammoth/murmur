from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, cast

from murmur import __version__
from murmur.archive_extract import ArchiveExtractionError, install_tui_binary_from_archive
from murmur.service_manager import ServiceManager


DEFAULT_REPOSITORY = os.environ.get("MURMUR_REPO", "mjmammoth/murmur")
DEFAULT_EXPECTED_SIGNING_FINGERPRINT = "031A071DD2F8736D5AB270EF239D1750F8F92826"
INSTALLER_HOME = Path("~/.local/share/murmur").expanduser()
INSTALLER_MANIFEST_NAME = "install-manifest.json"
INSTALLER_MANIFEST = INSTALLER_HOME / INSTALLER_MANIFEST_NAME
CHECKSUM_MANIFEST_NAMES = {"checksums.txt", "checksums.sha256", "checksums.sha256sum"}


def _secure_temp_root(base_dir: Path | None = None) -> Path:
    temp_root = (base_dir or INSTALLER_HOME).expanduser() / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        temp_root.chmod(0o700)
    except OSError:
        # Windows may not support POSIX chmod semantics; best effort is enough here.
        pass
    return temp_root


def _temporary_directory(*, prefix: str, base_dir: Path | None = None) -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix=prefix, dir=str(_secure_temp_root(base_dir)))


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
    if "Cellar/murmur" in executable_text:
        return True

    brew_bin = shutil.which("brew")
    if not brew_bin:
        return False

    try:
        result = subprocess.run(
            [brew_bin, "--prefix", "murmur"],
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
        "MURMUR_SIGNING_KEY_FINGERPRINT",
        DEFAULT_EXPECTED_SIGNING_FINGERPRINT,
    )
    fingerprint = _normalize_fingerprint(configured)
    if not fingerprint:
        raise UpgradeError(
            "Upgrade verification failed: signing key fingerprint is empty "
            "(set MURMUR_SIGNING_KEY_FINGERPRINT)."
        )
    return fingerprint


def _signing_key_url_for_repository(repository: str) -> str:
    override = os.environ.get("MURMUR_SIGNING_KEY_URL")
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
            "User-Agent": "murmur-upgrade",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw_payload = response.read().decode("utf-8")
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise UpgradeError("Failed to fetch release metadata: invalid JSON payload")
    return cast(dict[str, object], payload)


def _asset_name(asset: object) -> str:
    if not isinstance(asset, dict):
        return ""
    return str(asset.get("name") or "")


def _iter_named_assets(assets: list[object]) -> list[tuple[str, dict[str, object]]]:
    result: list[tuple[str, dict[str, object]]] = []
    for asset in assets:
        if isinstance(asset, dict):
            name = _asset_name(asset)
            if name:
                result.append((name, asset))
    return result


def _classify_assets(
    named_assets: list[tuple[str, dict[str, object]]],
    target_name: str,
) -> tuple[list[dict[str, object]], dict[str, object] | None, dict[str, object] | None]:
    wheel_assets: list[dict[str, object]] = []
    tui_asset: dict[str, object] | None = None
    checksums_asset: dict[str, object] | None = None
    expected_tui = f"murmur-tui-{target_name}.tar.gz"

    for name, asset in named_assets:
        if name.endswith(".whl"):
            wheel_assets.append(asset)
        if name == expected_tui:
            tui_asset = asset
        if name in CHECKSUM_MANIFEST_NAMES:
            checksums_asset = asset

    return wheel_assets, tui_asset, checksums_asset


def _find_signature_asset(
    named_assets: list[tuple[str, dict[str, object]]],
    checksums_name: str,
) -> dict[str, object] | None:
    exact_names = {f"{checksums_name}.asc", f"{checksums_name}.sig"}
    for name, asset in named_assets:
        if name in exact_names:
            return asset

    for name, asset in named_assets:
        if name.lower() in {"release.asc", "release.sig"}:
            return asset

    for name, asset in named_assets:
        lower = name.lower()
        if lower.endswith(".asc") and "checksum" in lower:
            return asset

    return None


def _validate_classified_assets(
    wheel_assets: list[dict[str, object]],
    tui_asset: dict[str, object] | None,
    checksums_asset: dict[str, object] | None,
    target_name: str,
) -> None:
    if not wheel_assets:
        raise UpgradeError("Release is missing wheel artifact")
    if len(wheel_assets) > 1:
        wheel_names = ", ".join(sorted(_asset_name(a) for a in wheel_assets))
        raise UpgradeError(
            f"Release contains multiple wheel artifacts; unable to select automatically: {wheel_names}"
        )
    if tui_asset is None:
        raise UpgradeError(f"Release is missing TUI artifact for target {target_name}")
    if checksums_asset is None:
        raise UpgradeError(
            "Release is missing checksum manifest (checksums.txt/.sha256/.sha256sum)"
        )


def _extract_asset_fields(asset: dict[str, object]) -> tuple[str, str]:
    name = str(asset.get("name") or "")
    url = str(asset.get("browser_download_url") or "")
    return name, url


def _fetch_release_payload(
    repository: str,
    normalized_tag: str | None,
) -> tuple[str, list[object]]:
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

    return tag, assets


def resolve_release_assets(
    *,
    repository: str = DEFAULT_REPOSITORY,
    requested_version: str | None = None,
    target: str | None = None,
) -> ReleaseAssetBundle:
    normalized_tag = normalize_version_tag(requested_version)
    target_name = target or detect_target()

    tag, raw_assets = _fetch_release_payload(repository, normalized_tag)
    named_assets = _iter_named_assets(raw_assets)

    wheel_assets, tui_asset, checksums_asset = _classify_assets(named_assets, target_name)
    _validate_classified_assets(wheel_assets, tui_asset, checksums_asset, target_name)

    checksums_name = _asset_name(checksums_asset)
    signature_asset = _find_signature_asset(named_assets, checksums_name)
    if signature_asset is None:
        raise UpgradeError("Release is missing checksum signature (.asc/.sig)")

    wheel_name, wheel_url = _extract_asset_fields(wheel_assets[0])
    tui_name, tui_url = _extract_asset_fields(tui_asset)  # type: ignore[arg-type]
    _, checksums_url = _extract_asset_fields(checksums_asset)  # type: ignore[arg-type]
    signature_name, signature_url = _extract_asset_fields(signature_asset)

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


def _download_to_file(url: str, destination: Path, *, max_attempts: int = 3) -> None:
    import logging
    import time
    import urllib.error

    logger = logging.getLogger(__name__)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "murmur-upgrade",
        },
    )
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                with destination.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            return
        except OSError as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = 2 ** (attempt - 1)
                logger.warning("Download attempt %d/%d failed: %s; retrying in %ds", attempt, max_attempts, exc, delay)
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


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
    for raw_line in manifest_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue

        digest_token, name_token = parts
        if len(digest_token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest_token):
            continue

        digest = digest_token.lower()
        name = name_token.strip()
        if name.startswith("*"):
            name = name[1:].strip()
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
    temp_dir_base: Path | None = None,
) -> None:
    gpg = shutil.which("gpg")
    if not gpg:
        raise UpgradeError(
            "Upgrade verification failed: 'gpg' is required. Install gpg and re-run upgrade."
        )

    expected_fingerprint = _expected_signing_fingerprint()
    signing_key_url = _signing_key_url_for_repository(repository)

    with _temporary_directory(
        prefix="murmur-upgrade-gpg-",
        base_dir=temp_dir_base,
    ) as tmp_dir:
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
    temp_dir_base: Path | None = None,
) -> None:
    _verify_release_signature(
        repository=bundle.repository,
        checksums_path=checksums_path,
        signature_path=signature_path,
        temp_dir_base=temp_dir_base,
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


def _expected_tui_binary_name(target: str) -> str:
    if target.startswith("windows-"):
        return "murmur-tui.exe"
    return "murmur-tui"


def _installed_version(python_executable: str) -> str:
    try:
        result = subprocess.run(
            [
                python_executable,
                "-c",
                "import murmur; print(murmur.__version__)",
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
        return "brew update && brew upgrade murmur"
    return "python -m pip install -U murmur"


def _download_release_to_temp(
    assets: ReleaseAssetBundle,
    tmp_root: Path,
    installer_home: Path,
) -> None:
    """Download and verify all release assets into a temporary directory."""
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
        temp_dir_base=installer_home,
    )


def _install_release_from_temp(
    assets: ReleaseAssetBundle,
    tmp_root: Path,
    installer_home: Path,
) -> None:
    """Install wheel and TUI binary from a verified temp directory."""
    wheel_path = tmp_root / assets.wheel_name
    tui_path = tmp_root / assets.tui_name

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", str(wheel_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stdout or "") + (exc.stderr or "")
        raise UpgradeError(f"pip install failed: {details.strip()}") from exc

    target_dir = installer_home / "tui" / assets.target
    expected_binary_name = _expected_tui_binary_name(assets.target)
    try:
        install_tui_binary_from_archive(
            archive_path=tui_path,
            target_dir=target_dir,
            expected_binary_name=expected_binary_name,
        )
    except ArchiveExtractionError as exc:
        raise UpgradeError(str(exc)) from exc


def _handle_upgrade_failure(
    exc: Exception,
    was_running: bool,
    manager: ServiceManager,
    host: str,
    port: int,
    status_indicator: bool,
) -> NoReturn:
    """Attempt to restart service after a failed upgrade and raise an appropriate error."""
    restart_exc: Exception | None = None
    if was_running:
        try:
            manager.start_background(host=host, port=port, status_indicator=status_indicator)
        except Exception as restart_error:
            restart_exc = restart_error

    if restart_exc is not None:
        base_msg = str(exc) if isinstance(exc, UpgradeError) else f"Upgrade failed: {exc}"
        raise UpgradeError(
            f"{base_msg}; additionally failed to restart service: {restart_exc}"
        ) from exc
    if isinstance(exc, UpgradeError):
        raise exc
    raise UpgradeError(f"Upgrade failed: {exc}") from exc


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

        with _temporary_directory(
            prefix="murmur-upgrade-",
            base_dir=installer_home,
        ) as tmp_dir:
            tmp_root = Path(tmp_dir)
            _download_release_to_temp(assets, tmp_root, installer_home)
            _install_release_from_temp(assets, tmp_root, installer_home)

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
        _handle_upgrade_failure(exc, was_running, manager, host, port, status_indicator)
