from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

from whisper_local import upgrade
from whisper_local.upgrade import ReleaseAssetBundle, UpgradeActionRequired, UpgradeError


def test_read_install_manifest_valid_payload(tmp_path: Path) -> None:
    manifest_path = tmp_path / "install-manifest.json"
    manifest_path.write_text(
        '{"channel":"installer","installer_home":"/tmp/whisper.local"}',
        encoding="utf-8",
    )

    manifest = upgrade.read_install_manifest(manifest_path)

    assert manifest is not None
    assert manifest.get("channel") == "installer"


def test_read_install_manifest_invalid_payload_returns_none(tmp_path: Path) -> None:
    manifest_path = tmp_path / "install-manifest.json"
    manifest_path.write_text("[]", encoding="utf-8")

    assert upgrade.read_install_manifest(manifest_path) is None


def test_detect_install_channel_manifest_does_not_override_non_installer_executable(
    tmp_path: Path,
) -> None:
    installer_home = tmp_path / "whisper-local"
    (installer_home / "venv").mkdir(parents=True, exist_ok=True)
    (installer_home / "tui").mkdir(parents=True, exist_ok=True)
    (installer_home / upgrade.INSTALLER_MANIFEST_NAME).write_text(
        (
            "{"
            '"channel":"installer",'
            f'"installer_home":"{installer_home}"'
            "}"
        ),
        encoding="utf-8",
    )

    with patch("whisper_local.upgrade._looks_like_homebrew_install", return_value=False):
        channel = upgrade.detect_install_channel(
            executable="/usr/local/bin/python3",
            installer_home=installer_home,
        )

    assert channel == "pip"


def test_detect_install_channel_manifest_does_not_override_homebrew_executable(tmp_path: Path) -> None:
    installer_home = tmp_path / "whisper-local"
    (installer_home / "venv").mkdir(parents=True, exist_ok=True)
    (installer_home / "tui").mkdir(parents=True, exist_ok=True)
    (installer_home / upgrade.INSTALLER_MANIFEST_NAME).write_text(
        (
            "{"
            '"channel":"installer",'
            f'"installer_home":"{installer_home}"'
            "}"
        ),
        encoding="utf-8",
    )

    channel = upgrade.detect_install_channel(
        executable="/opt/homebrew/Cellar/whisper-local/1.0.0/bin/python3",
        installer_home=installer_home,
    )

    assert channel == "homebrew"


def test_detect_install_channel_installer(tmp_path: Path) -> None:
    installer_home = tmp_path / "whisper-local"
    executable = installer_home / "venv" / "bin" / "python"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("", encoding="utf-8")
    (installer_home / "tui").mkdir(parents=True, exist_ok=True)

    channel = upgrade.detect_install_channel(
        executable=str(executable),
        installer_home=installer_home,
    )

    assert channel == "installer"


def test_detect_install_channel_installer_without_tui_dir(tmp_path: Path) -> None:
    installer_home = tmp_path / "whisper-local"
    executable = installer_home / "venv" / "bin" / "python"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("", encoding="utf-8")

    channel = upgrade.detect_install_channel(
        executable=str(executable),
        installer_home=installer_home,
    )

    assert channel == "installer"


def test_detect_install_channel_stale_manifest_falls_back_to_path_heuristic(tmp_path: Path) -> None:
    installer_home = tmp_path / "whisper-local"
    executable = installer_home / "venv" / "bin" / "python"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("", encoding="utf-8")
    (installer_home / "tui").mkdir(parents=True, exist_ok=True)
    (installer_home / upgrade.INSTALLER_MANIFEST_NAME).write_text(
        '{"channel":"installer","installer_home":"/different/path"}',
        encoding="utf-8",
    )

    channel = upgrade.detect_install_channel(
        executable=str(executable),
        installer_home=installer_home,
    )

    assert channel == "installer"


def test_detect_install_channel_stale_manifest_falls_back_to_pip(tmp_path: Path) -> None:
    installer_home = tmp_path / "whisper-local"
    installer_home.mkdir(parents=True, exist_ok=True)
    (installer_home / upgrade.INSTALLER_MANIFEST_NAME).write_text(
        '{"channel":"installer","installer_home":"/different/path"}',
        encoding="utf-8",
    )

    with patch("whisper_local.upgrade._looks_like_homebrew_install", return_value=False):
        channel = upgrade.detect_install_channel(
            executable="/usr/local/bin/python3",
            installer_home=installer_home,
        )

    assert channel == "pip"


def test_detect_install_channel_homebrew_by_executable_path(tmp_path: Path) -> None:
    channel = upgrade.detect_install_channel(
        executable="/opt/homebrew/Cellar/whisper-local/1.0.0/bin/python3",
        installer_home=tmp_path,
    )

    assert channel == "homebrew"


def test_detect_install_channel_pip_fallback(tmp_path: Path) -> None:
    with patch("whisper_local.upgrade._looks_like_homebrew_install", return_value=False):
        channel = upgrade.detect_install_channel(
            executable="/usr/local/bin/python3",
            installer_home=tmp_path,
        )

    assert channel == "pip"


def test_looks_like_homebrew_install_requires_executable_under_prefix() -> None:
    result = SimpleNamespace(returncode=0, stdout="/opt/homebrew/opt/whisper-local\n", stderr="")
    with patch("whisper_local.upgrade.shutil.which", return_value="/opt/homebrew/bin/brew"), patch(
        "whisper_local.upgrade.subprocess.run", return_value=result
    ):
        assert (
            upgrade._looks_like_homebrew_install(Path("/opt/homebrew/opt/whisper-local/bin/python3"))
            is True
        )


def test_looks_like_homebrew_install_rejects_executable_outside_prefix() -> None:
    result = SimpleNamespace(returncode=0, stdout="/opt/homebrew/opt/whisper-local\n", stderr="")
    with patch("whisper_local.upgrade.shutil.which", return_value="/opt/homebrew/bin/brew"), patch(
        "whisper_local.upgrade.subprocess.run", return_value=result
    ):
        assert upgrade._looks_like_homebrew_install(Path("/usr/local/bin/python3")) is False


def test_normalize_version_tag() -> None:
    assert upgrade.normalize_version_tag(None) is None
    assert upgrade.normalize_version_tag("latest") is None
    assert upgrade.normalize_version_tag("0.2.0") == "v0.2.0"
    assert upgrade.normalize_version_tag("v0.2.0") == "v0.2.0"


def test_resolve_release_assets_uses_target_bundle() -> None:
    payload = {
        "tag_name": "v0.2.0",
        "assets": [
            {
                "name": "whisper_local-0.2.0-py3-none-any.whl",
                "browser_download_url": "https://example.invalid/whl",
            },
            {
                "name": "whisper-local-tui-linux-x64.tar.gz",
                "browser_download_url": "https://example.invalid/tui",
            },
            {
                "name": "checksums.txt",
                "browser_download_url": "https://example.invalid/checksums",
            },
            {
                "name": "checksums.txt.asc",
                "browser_download_url": "https://example.invalid/checksums.sig",
            },
        ],
    }

    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        result = upgrade.resolve_release_assets(
            repository="owner/repo",
            requested_version="v0.2.0",
            target="linux-x64",
        )

    assert result.repository == "owner/repo"
    assert result.tag == "v0.2.0"
    assert result.target == "linux-x64"
    assert result.wheel_url == "https://example.invalid/whl"
    assert result.tui_url == "https://example.invalid/tui"
    assert result.checksums_name == "checksums.txt"
    assert result.checksums_url == "https://example.invalid/checksums"
    assert result.signature_name == "checksums.txt.asc"
    assert result.signature_url == "https://example.invalid/checksums.sig"


def test_resolve_release_assets_missing_target_tui_raises() -> None:
    payload = {
        "tag_name": "v0.2.0",
        "assets": [
            {
                "name": "whisper_local-0.2.0-py3-none-any.whl",
                "browser_download_url": "https://example.invalid/whl",
            }
        ],
    }

    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError) as exc_info:
            upgrade.resolve_release_assets(target="linux-x64")

    assert "TUI artifact" in str(exc_info.value)


def test_resolve_release_assets_multiple_wheels_raises() -> None:
    payload = {
        "tag_name": "v0.2.0",
        "assets": [
            {
                "name": "whisper_local-0.2.0-py3-none-any.whl",
                "browser_download_url": "https://example.invalid/whl1",
            },
            {
                "name": "whisper_local-0.2.0-cp312-cp312-manylinux.whl",
                "browser_download_url": "https://example.invalid/whl2",
            },
            {
                "name": "whisper-local-tui-linux-x64.tar.gz",
                "browser_download_url": "https://example.invalid/tui",
            },
            {
                "name": "checksums.txt",
                "browser_download_url": "https://example.invalid/checksums",
            },
            {
                "name": "checksums.txt.asc",
                "browser_download_url": "https://example.invalid/checksums.sig",
            },
        ],
    }

    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="multiple wheel artifacts"):
            upgrade.resolve_release_assets(target="linux-x64")


def test_resolve_release_assets_missing_checksums_raises() -> None:
    payload = {
        "tag_name": "v0.2.0",
        "assets": [
            {
                "name": "whisper_local-0.2.0-py3-none-any.whl",
                "browser_download_url": "https://example.invalid/whl",
            },
            {
                "name": "whisper-local-tui-linux-x64.tar.gz",
                "browser_download_url": "https://example.invalid/tui",
            },
        ],
    }

    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="missing checksum manifest"):
            upgrade.resolve_release_assets(target="linux-x64")


def test_resolve_release_assets_missing_signature_raises() -> None:
    payload = {
        "tag_name": "v0.2.0",
        "assets": [
            {
                "name": "whisper_local-0.2.0-py3-none-any.whl",
                "browser_download_url": "https://example.invalid/whl",
            },
            {
                "name": "whisper-local-tui-linux-x64.tar.gz",
                "browser_download_url": "https://example.invalid/tui",
            },
            {
                "name": "checksums.txt",
                "browser_download_url": "https://example.invalid/checksums",
            },
        ],
    }

    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="missing checksum signature"):
            upgrade.resolve_release_assets(target="linux-x64")


def test_verify_release_signature_requires_gpg(tmp_path: Path) -> None:
    checksums = tmp_path / "checksums.txt"
    signature = tmp_path / "checksums.txt.asc"
    checksums.write_text("", encoding="utf-8")
    signature.write_text("", encoding="utf-8")

    with patch("whisper_local.upgrade.shutil.which", return_value=None):
        with pytest.raises(UpgradeError, match="'gpg' is required"):
            upgrade._verify_release_signature(
                repository="owner/repo",
                checksums_path=checksums,
                signature_path=signature,
            )


def test_replace_tui_binary_uses_tar_data_filter(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    extract_root = tmp_path / "extract-root"
    extract_root.mkdir(parents=True, exist_ok=True)
    (extract_root / "whisper-local-tui").write_text("binary", encoding="utf-8")

    temp_dir_ctx = Mock()
    temp_dir_ctx.__enter__ = Mock(return_value=str(extract_root))
    temp_dir_ctx.__exit__ = Mock(return_value=False)

    with patch("whisper_local.upgrade.tempfile.TemporaryDirectory", return_value=temp_dir_ctx), patch(
        "whisper_local.upgrade.tarfile.open"
    ) as mock_tar_open:
        tar_handle = mock_tar_open.return_value.__enter__.return_value
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )

    tar_handle.extractall.assert_called_once_with(extract_root, filter="data")


def test_run_upgrade_installer_running_service_restarts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade.sys, "platform", "linux")

    manager = Mock()
    manager.status.return_value = SimpleNamespace(
        running=True,
        host="127.0.0.1",
        port=8999,
        status_indicator_pid=None,
    )
    assets = ReleaseAssetBundle(
        repository="owner/repo",
        tag="v0.2.0",
        wheel_name="whisper_local-0.2.0-py3-none-any.whl",
        wheel_url="https://example.invalid/whl",
        tui_name="whisper-local-tui-linux-x64.tar.gz",
        tui_url="https://example.invalid/tui",
        checksums_name="checksums.txt",
        checksums_url="https://example.invalid/checksums",
        signature_name="checksums.txt.asc",
        signature_url="https://example.invalid/checksums.sig",
        target="linux-x64",
    )

    with patch("whisper_local.upgrade.detect_install_channel", return_value="installer"), patch(
        "whisper_local.upgrade.resolve_release_assets", return_value=assets
    ), patch("whisper_local.upgrade._download_to_file"), patch(
        "whisper_local.upgrade._replace_tui_binary"
    ), patch(
        "whisper_local.upgrade._verify_downloaded_release_assets"
    ) as mock_verify_assets, patch(
        "whisper_local.upgrade._installed_version", side_effect=["0.1.0", "0.2.0"]
    ), patch("whisper_local.upgrade.subprocess.run"):
        result = upgrade.run_upgrade(
            requested_version="v0.2.0",
            installer_home=tmp_path,
            service_manager=manager,
        )

    assert result.tag == "v0.2.0"
    assert result.previous_version == "0.1.0"
    assert result.new_version == "0.2.0"
    assert result.restarted_service is True
    assert manager.mock_calls[0] == call.status()
    assert manager.mock_calls[1] == call.stop()
    manager.start_background.assert_called_once_with(
        host="127.0.0.1",
        port=8999,
        status_indicator=False,
    )
    mock_verify_assets.assert_called_once()


def test_run_upgrade_installer_when_service_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade.sys, "platform", "linux")

    manager = Mock()
    manager.status.return_value = SimpleNamespace(
        running=False,
        host=None,
        port=None,
        status_indicator_pid=None,
    )
    assets = ReleaseAssetBundle(
        repository="owner/repo",
        tag="v0.2.0",
        wheel_name="whisper_local-0.2.0-py3-none-any.whl",
        wheel_url="https://example.invalid/whl",
        tui_name="whisper-local-tui-linux-x64.tar.gz",
        tui_url="https://example.invalid/tui",
        checksums_name="checksums.txt",
        checksums_url="https://example.invalid/checksums",
        signature_name="checksums.txt.asc",
        signature_url="https://example.invalid/checksums.sig",
        target="linux-x64",
    )

    with patch("whisper_local.upgrade.detect_install_channel", return_value="installer"), patch(
        "whisper_local.upgrade.resolve_release_assets", return_value=assets
    ), patch("whisper_local.upgrade._download_to_file"), patch(
        "whisper_local.upgrade._replace_tui_binary"
    ), patch(
        "whisper_local.upgrade._verify_downloaded_release_assets"
    ), patch("whisper_local.upgrade._installed_version", side_effect=["0.1.0", "0.2.0"]), patch(
        "whisper_local.upgrade.subprocess.run"
    ):
        result = upgrade.run_upgrade(
            requested_version=None,
            installer_home=tmp_path,
            service_manager=manager,
        )

    assert result.restarted_service is False
    manager.stop.assert_not_called()
    manager.start_background.assert_not_called()


def test_run_upgrade_non_installer_returns_guidance(tmp_path: Path) -> None:
    with patch("whisper_local.upgrade.detect_install_channel", return_value="homebrew"):
        with pytest.raises(UpgradeActionRequired) as exc_info:
            upgrade.run_upgrade(installer_home=tmp_path)

    assert exc_info.value.channel == "homebrew"
    assert "brew upgrade whisper-local" in exc_info.value.command


def test_run_upgrade_failure_attempts_service_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upgrade.sys, "platform", "linux")

    manager = Mock()
    manager.status.return_value = SimpleNamespace(
        running=True,
        host="localhost",
        port=7878,
        status_indicator_pid=None,
    )
    assets = ReleaseAssetBundle(
        repository="owner/repo",
        tag="v0.2.0",
        wheel_name="whisper_local-0.2.0-py3-none-any.whl",
        wheel_url="https://example.invalid/whl",
        tui_name="whisper-local-tui-linux-x64.tar.gz",
        tui_url="https://example.invalid/tui",
        checksums_name="checksums.txt",
        checksums_url="https://example.invalid/checksums",
        signature_name="checksums.txt.asc",
        signature_url="https://example.invalid/checksums.sig",
        target="linux-x64",
    )

    with patch("whisper_local.upgrade.detect_install_channel", return_value="installer"), patch(
        "whisper_local.upgrade.resolve_release_assets", return_value=assets
    ), patch(
        "whisper_local.upgrade._download_to_file",
        side_effect=RuntimeError("download failed"),
    ), patch("whisper_local.upgrade._installed_version", return_value="0.1.0"):
        with pytest.raises(UpgradeError) as exc_info:
            upgrade.run_upgrade(installer_home=tmp_path, service_manager=manager)

    assert "download failed" in str(exc_info.value)
    manager.stop.assert_called_once()
    manager.start_background.assert_called_once_with(
        host="localhost",
        port=7878,
        status_indicator=False,
    )


def test_run_upgrade_failure_surfaces_restart_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upgrade.sys, "platform", "linux")

    manager = Mock()
    manager.status.return_value = SimpleNamespace(
        running=True,
        host="localhost",
        port=7878,
        status_indicator_pid=None,
    )
    manager.start_background.side_effect = RuntimeError("restart failed")
    assets = ReleaseAssetBundle(
        repository="owner/repo",
        tag="v0.2.0",
        wheel_name="whisper_local-0.2.0-py3-none-any.whl",
        wheel_url="https://example.invalid/whl",
        tui_name="whisper-local-tui-linux-x64.tar.gz",
        tui_url="https://example.invalid/tui",
        checksums_name="checksums.txt",
        checksums_url="https://example.invalid/checksums",
        signature_name="checksums.txt.asc",
        signature_url="https://example.invalid/checksums.sig",
        target="linux-x64",
    )

    with patch("whisper_local.upgrade.detect_install_channel", return_value="installer"), patch(
        "whisper_local.upgrade.resolve_release_assets", return_value=assets
    ), patch(
        "whisper_local.upgrade._download_to_file",
        side_effect=RuntimeError("download failed"),
    ), patch("whisper_local.upgrade._installed_version", return_value="0.1.0"):
        with pytest.raises(UpgradeError) as exc_info:
            upgrade.run_upgrade(installer_home=tmp_path, service_manager=manager)

    assert "download failed" in str(exc_info.value)
    assert "restart failed" in str(exc_info.value)
    manager.stop.assert_called_once()
    manager.start_background.assert_called_once_with(
        host="localhost",
        port=7878,
        status_indicator=False,
    )
