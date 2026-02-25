from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

from whisper_local import upgrade
from whisper_local.upgrade import ReleaseAssetBundle, UpgradeActionRequired, UpgradeError


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
        target="linux-x64",
    )

    with patch("whisper_local.upgrade.detect_install_channel", return_value="installer"), patch(
        "whisper_local.upgrade.resolve_release_assets", return_value=assets
    ), patch("whisper_local.upgrade._download_to_file"), patch(
        "whisper_local.upgrade._replace_tui_binary"
    ), patch("whisper_local.upgrade._installed_version", side_effect=["0.1.0", "0.2.0"]), patch(
        "whisper_local.upgrade.subprocess.run"
    ):
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
        target="linux-x64",
    )

    with patch("whisper_local.upgrade.detect_install_channel", return_value="installer"), patch(
        "whisper_local.upgrade.resolve_release_assets", return_value=assets
    ), patch("whisper_local.upgrade._download_to_file"), patch(
        "whisper_local.upgrade._replace_tui_binary"
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
