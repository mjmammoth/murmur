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


def test_parse_checksums_manifest_parses_sha256_and_optional_star(tmp_path: Path) -> None:
    manifest_path = tmp_path / "checksums.txt"
    manifest_path.write_text(
        "\n".join(
            [
                "# comment",
                "invalid line",
                "A" * 64 + "  whisper_local-0.2.0-py3-none-any.whl",
                "b" * 64 + "\t*whisper-local-tui-linux-x64.tar.gz",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = upgrade._parse_checksums_manifest(manifest_path)

    assert parsed == {
        "whisper_local-0.2.0-py3-none-any.whl": "a" * 64,
        "whisper-local-tui-linux-x64.tar.gz": "b" * 64,
    }


def test_parse_checksums_manifest_raises_when_no_valid_entries(tmp_path: Path) -> None:
    manifest_path = tmp_path / "checksums.txt"
    manifest_path.write_text(
        "\n".join(
            [
                "# comment",
                "not-a-checksum file.whl",
                "abc123",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(UpgradeError, match="checksum manifest is empty or invalid"):
        upgrade._parse_checksums_manifest(manifest_path)


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
        "whisper_local.upgrade.install_tui_binary_from_archive"
    ) as mock_extract, patch(
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
    assert mock_extract.call_count == 1
    extract_kwargs = mock_extract.call_args.kwargs
    assert extract_kwargs["target_dir"] == tmp_path / "tui" / "linux-x64"
    assert extract_kwargs["expected_binary_name"] == "whisper-local-tui"
    assert extract_kwargs["archive_path"].name == assets.tui_name


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
        "whisper_local.upgrade.install_tui_binary_from_archive"
    ) as mock_extract, patch(
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
    assert mock_extract.call_count == 1
    extract_kwargs = mock_extract.call_args.kwargs
    assert extract_kwargs["target_dir"] == tmp_path / "tui" / "linux-x64"
    assert extract_kwargs["expected_binary_name"] == "whisper-local-tui"
    assert extract_kwargs["archive_path"].name == assets.tui_name


def test_run_upgrade_installer_maps_windows_binary_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        tui_name="whisper-local-tui-windows-x64.tar.gz",
        tui_url="https://example.invalid/tui",
        checksums_name="checksums.txt",
        checksums_url="https://example.invalid/checksums",
        signature_name="checksums.txt.asc",
        signature_url="https://example.invalid/checksums.sig",
        target="windows-x64",
    )

    with patch("whisper_local.upgrade.detect_install_channel", return_value="installer"), patch(
        "whisper_local.upgrade.resolve_release_assets", return_value=assets
    ), patch("whisper_local.upgrade._download_to_file"), patch(
        "whisper_local.upgrade.install_tui_binary_from_archive"
    ) as mock_extract, patch(
        "whisper_local.upgrade._verify_downloaded_release_assets"
    ), patch("whisper_local.upgrade._installed_version", side_effect=["0.1.0", "0.2.0"]), patch(
        "whisper_local.upgrade.subprocess.run"
    ):
        upgrade.run_upgrade(
            requested_version=None,
            installer_home=tmp_path,
            service_manager=manager,
        )

    assert mock_extract.call_count == 1
    assert mock_extract.call_args.kwargs["expected_binary_name"] == "whisper-local-tui.exe"


def test_run_upgrade_wraps_archive_extraction_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        "whisper_local.upgrade.install_tui_binary_from_archive",
        side_effect=upgrade.ArchiveExtractionError("bad archive"),
    ), patch(
        "whisper_local.upgrade._verify_downloaded_release_assets"
    ), patch(
        "whisper_local.upgrade._installed_version", side_effect=["0.1.0", "0.2.0"]
    ), patch("whisper_local.upgrade.subprocess.run"):
        with pytest.raises(UpgradeError, match="bad archive"):
            upgrade.run_upgrade(
                requested_version="v0.2.0",
                installer_home=tmp_path,
                service_manager=manager,
            )


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


# ---------------------------------------------------------------------------
# detect_target
# ---------------------------------------------------------------------------


def test_detect_target_darwin_arm64():
    with patch("whisper_local.upgrade.sys.platform", "darwin"), \
         patch("whisper_local.upgrade.os.uname", return_value=SimpleNamespace(machine="arm64"), create=True):
        assert upgrade.detect_target() == "darwin-arm64"


def test_detect_target_darwin_x64():
    with patch("whisper_local.upgrade.sys.platform", "darwin"), \
         patch("whisper_local.upgrade.os.uname", return_value=SimpleNamespace(machine="x86_64"), create=True):
        assert upgrade.detect_target() == "darwin-x64"


def test_detect_target_linux_x64():
    with patch("whisper_local.upgrade.sys.platform", "linux"), \
         patch("whisper_local.upgrade.os.uname", return_value=SimpleNamespace(machine="x86_64"), create=True):
        assert upgrade.detect_target() == "linux-x64"


def test_detect_target_linux_arm64():
    with patch("whisper_local.upgrade.sys.platform", "linux"), \
         patch("whisper_local.upgrade.os.uname", return_value=SimpleNamespace(machine="aarch64"), create=True):
        assert upgrade.detect_target() == "linux-arm64"


def test_detect_target_windows_x64():
    with patch("whisper_local.upgrade.sys.platform", "win32"), \
         patch("whisper_local.upgrade.os.uname", return_value=SimpleNamespace(machine="x86_64"), create=True):
        assert upgrade.detect_target() == "windows-x64"


def test_detect_target_unsupported():
    with patch("whisper_local.upgrade.sys.platform", "freebsd"), \
         patch("whisper_local.upgrade.os.uname", return_value=SimpleNamespace(machine="mips"), create=True):
        with pytest.raises(UpgradeError, match="Unsupported"):
            upgrade.detect_target()


# ---------------------------------------------------------------------------
# _expected_signing_fingerprint / _signing_key_url_for_repository
# ---------------------------------------------------------------------------


def test_expected_signing_fingerprint_default(monkeypatch):
    monkeypatch.delenv("WHISPER_LOCAL_SIGNING_KEY_FINGERPRINT", raising=False)
    result = upgrade._expected_signing_fingerprint()
    assert len(result) > 0


def test_expected_signing_fingerprint_from_env(monkeypatch):
    monkeypatch.setenv("WHISPER_LOCAL_SIGNING_KEY_FINGERPRINT", "AB CD EF 12")
    result = upgrade._expected_signing_fingerprint()
    assert result == "ABCDEF12"


def test_expected_signing_fingerprint_empty(monkeypatch):
    monkeypatch.setenv("WHISPER_LOCAL_SIGNING_KEY_FINGERPRINT", "   ")
    with pytest.raises(UpgradeError, match="empty"):
        upgrade._expected_signing_fingerprint()


def test_signing_key_url_default():
    url = upgrade._signing_key_url_for_repository("owner/repo")
    assert url == "https://github.com/owner.gpg"


def test_signing_key_url_override(monkeypatch):
    monkeypatch.setenv("WHISPER_LOCAL_SIGNING_KEY_URL", "https://example.com/key.gpg")
    url = upgrade._signing_key_url_for_repository("owner/repo")
    assert url == "https://example.com/key.gpg"


def test_signing_key_url_empty_owner():
    with pytest.raises(UpgradeError, match="invalid repository"):
        upgrade._signing_key_url_for_repository("/repo")


# ---------------------------------------------------------------------------
# _normalize_fingerprint
# ---------------------------------------------------------------------------


def test_normalize_fingerprint():
    assert upgrade._normalize_fingerprint("ab cd ef") == "ABCDEF"


# ---------------------------------------------------------------------------
# _parse_checksums_manifest
# ---------------------------------------------------------------------------


def test_parse_checksums_manifest_valid(tmp_path: Path):
    manifest = tmp_path / "checksums.txt"
    digest = "a" * 64
    manifest.write_text(f"{digest}  myfile.whl\n", encoding="utf-8")
    result = upgrade._parse_checksums_manifest(manifest)
    assert result == {"myfile.whl": digest}


def test_parse_checksums_manifest_star_prefix(tmp_path: Path):
    manifest = tmp_path / "checksums.txt"
    digest = "b" * 64
    manifest.write_text(f"{digest} *myfile.bin\n", encoding="utf-8")
    result = upgrade._parse_checksums_manifest(manifest)
    assert result == {"myfile.bin": digest}


def test_parse_checksums_manifest_empty(tmp_path: Path):
    manifest = tmp_path / "checksums.txt"
    manifest.write_text("# comment only\n", encoding="utf-8")
    with pytest.raises(UpgradeError, match="empty or invalid"):
        upgrade._parse_checksums_manifest(manifest)


def test_parse_checksums_manifest_invalid_digest(tmp_path: Path):
    manifest = tmp_path / "checksums.txt"
    manifest.write_text("shortdigest myfile.bin\n", encoding="utf-8")
    with pytest.raises(UpgradeError, match="empty or invalid"):
        upgrade._parse_checksums_manifest(manifest)


# ---------------------------------------------------------------------------
# _checksum_for_asset
# ---------------------------------------------------------------------------


def test_checksum_for_asset_direct_match():
    checksums = {"myfile.whl": "abc123"}
    assert upgrade._checksum_for_asset("myfile.whl", checksums) == "abc123"


def test_checksum_for_asset_basename_match():
    checksums = {"path/to/myfile.whl": "abc123"}
    assert upgrade._checksum_for_asset("myfile.whl", checksums) == "abc123"


def test_checksum_for_asset_multiple_matches():
    checksums = {"a/myfile.whl": "abc", "b/myfile.whl": "def"}
    with pytest.raises(UpgradeError, match="multiple"):
        upgrade._checksum_for_asset("myfile.whl", checksums)


def test_checksum_for_asset_missing():
    with pytest.raises(UpgradeError, match="missing"):
        upgrade._checksum_for_asset("myfile.whl", {})


# ---------------------------------------------------------------------------
# _sha256_file
# ---------------------------------------------------------------------------


def test_sha256_file(tmp_path: Path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello")
    import hashlib
    expected = hashlib.sha256(b"hello").hexdigest()
    assert upgrade._sha256_file(f) == expected


# ---------------------------------------------------------------------------
# _run_command_or_error
# ---------------------------------------------------------------------------


def test_run_command_or_error_success():
    with patch(
        "whisper_local.upgrade.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout="hello\n", stderr=""),
    ):
        result = upgrade._run_command_or_error(["echo", "hello"])
    assert "hello" in result


def test_run_command_or_error_failure():
    with patch(
        "whisper_local.upgrade.subprocess.run",
        return_value=SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    ):
        with pytest.raises(UpgradeError, match="Upgrade verification failed"):
            upgrade._run_command_or_error(["false"])


def test_run_command_or_error_not_found():
    with patch(
        "whisper_local.upgrade.subprocess.run",
        side_effect=FileNotFoundError("binary not found"),
    ):
        with pytest.raises(UpgradeError, match="Upgrade verification failed"):
            upgrade._run_command_or_error(["nonexistent_binary_12345"])


# ---------------------------------------------------------------------------
# _expected_tui_binary_name / _installed_version / _guidance_command_for_channel
# ---------------------------------------------------------------------------


def test_expected_tui_binary_name_windows():
    assert upgrade._expected_tui_binary_name("windows-x64") == "whisper-local-tui.exe"


def test_expected_tui_binary_name_unix():
    assert upgrade._expected_tui_binary_name("darwin-arm64") == "whisper-local-tui"


def test_installed_version_success():
    with patch("whisper_local.upgrade.subprocess.run") as mock_run:
        mock_run.return_value = Mock(stdout="1.2.3\n", returncode=0)
        result = upgrade._installed_version("python3")
    assert result == "1.2.3"


def test_installed_version_failure():
    with patch("whisper_local.upgrade.subprocess.run", side_effect=Exception("fail")):
        result = upgrade._installed_version("python3")
    # Falls back to __version__
    assert result == upgrade.__version__


def test_guidance_command_homebrew():
    result = upgrade._guidance_command_for_channel("homebrew")
    assert "brew" in result


def test_guidance_command_pip():
    result = upgrade._guidance_command_for_channel("pip")
    assert "pip" in result


# ---------------------------------------------------------------------------
# detect_install_channel
# ---------------------------------------------------------------------------


def test_detect_install_channel_installer_relative_to(tmp_path: Path):
    venv = tmp_path / "venv" / "bin"
    venv.mkdir(parents=True)
    exe = venv / "python"
    exe.write_text("#!/usr/bin/env python", encoding="utf-8")

    result = upgrade.detect_install_channel(
        executable=str(exe),
        installer_home=tmp_path,
    )
    assert result == "installer"


def test_detect_install_channel_homebrew(tmp_path: Path):
    exe_path = tmp_path / "Cellar" / "whisper-local" / "bin" / "python"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("#!/usr/bin/env python", encoding="utf-8")

    result = upgrade.detect_install_channel(
        executable=str(exe_path),
        installer_home=tmp_path / "nonexistent",
    )
    assert result == "homebrew"


def test_detect_install_channel_pip(tmp_path: Path):
    exe = tmp_path / "python"
    exe.write_text("#!/usr/bin/env python", encoding="utf-8")

    with patch("whisper_local.upgrade._looks_like_homebrew_install", return_value=False):
        result = upgrade.detect_install_channel(
            executable=str(exe),
            installer_home=tmp_path / "nonexistent",
        )
    assert result == "pip"


# ---------------------------------------------------------------------------
# _download_to_file
# ---------------------------------------------------------------------------


def test_download_to_file(tmp_path: Path):
    dest = tmp_path / "downloaded.bin"
    mock_response = Mock()
    mock_response.read.side_effect = [b"chunk1", b"chunk2", b""]
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)

    with patch("whisper_local.upgrade.urllib.request.urlopen", return_value=mock_response):
        upgrade._download_to_file("https://example.com/file.bin", dest)
    assert dest.read_bytes() == b"chunk1chunk2"


# ---------------------------------------------------------------------------
# _looks_like_homebrew_install
# ---------------------------------------------------------------------------


def test_looks_like_homebrew_cellar():
    exe = Path("/opt/homebrew/Cellar/whisper-local/1.0/bin/python")
    assert upgrade._looks_like_homebrew_install(exe) is True


def test_looks_like_homebrew_no_brew(tmp_path: Path):
    exe = tmp_path / "python"
    with patch("whisper_local.upgrade.shutil.which", return_value=None):
        assert upgrade._looks_like_homebrew_install(exe) is False


def test_looks_like_homebrew_brew_check_fail(tmp_path: Path):
    exe = tmp_path / "python"
    with patch("whisper_local.upgrade.shutil.which", return_value="/usr/local/bin/brew"), \
         patch("whisper_local.upgrade.subprocess.run", side_effect=Exception("fail")):
        assert upgrade._looks_like_homebrew_install(exe) is False


def test_looks_like_homebrew_brew_nonzero_rc(tmp_path: Path):
    exe = tmp_path / "python"
    mock_result = Mock(returncode=1, stdout="", stderr="")
    with patch("whisper_local.upgrade.shutil.which", return_value="/usr/local/bin/brew"), \
         patch("whisper_local.upgrade.subprocess.run", return_value=mock_result):
        assert upgrade._looks_like_homebrew_install(exe) is False


def test_looks_like_homebrew_brew_empty_prefix(tmp_path: Path):
    exe = tmp_path / "python"
    mock_result = Mock(returncode=0, stdout="", stderr="")
    with patch("whisper_local.upgrade.shutil.which", return_value="/usr/local/bin/brew"), \
         patch("whisper_local.upgrade.subprocess.run", return_value=mock_result):
        assert upgrade._looks_like_homebrew_install(exe) is False


def test_looks_like_homebrew_relative_to_prefix(tmp_path: Path):
    prefix = tmp_path / "homebrew"
    exe = prefix / "bin" / "python"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/usr/bin/env python", encoding="utf-8")
    mock_result = Mock(returncode=0, stdout=str(prefix), stderr="")
    with patch("whisper_local.upgrade.shutil.which", return_value="/usr/local/bin/brew"), \
         patch("whisper_local.upgrade.subprocess.run", return_value=mock_result):
        assert upgrade._looks_like_homebrew_install(exe) is True


# ---------------------------------------------------------------------------
# _github_get_json
# ---------------------------------------------------------------------------


def test_github_get_json_success():
    mock_response = Mock()
    mock_response.read.return_value = b'{"key": "value"}'
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)

    with patch("whisper_local.upgrade.urllib.request.urlopen", return_value=mock_response):
        result = upgrade._github_get_json("https://api.github.com/test")
    assert result == {"key": "value"}


def test_github_get_json_invalid_json_type():
    mock_response = Mock()
    mock_response.read.return_value = b'["not", "a", "dict"]'
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)

    with patch("whisper_local.upgrade.urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(UpgradeError, match="invalid JSON"):
            upgrade._github_get_json("https://api.github.com/test")


# ---------------------------------------------------------------------------
# resolve_release_assets
# ---------------------------------------------------------------------------


def _make_asset(name: str, url: str = "https://example.com/file") -> dict:
    return {"name": name, "browser_download_url": url}


def test_resolve_release_assets_success():
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            _make_asset("whisper_local-1.0.0.whl", "https://example.com/whl"),
            _make_asset("whisper-local-tui-darwin-arm64.tar.gz", "https://example.com/tui"),
            _make_asset("checksums.txt", "https://example.com/checksums"),
            _make_asset("checksums.txt.asc", "https://example.com/sig"),
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        bundle = upgrade.resolve_release_assets(target="darwin-arm64")
    assert bundle.tag == "v1.0.0"
    assert bundle.wheel_url == "https://example.com/whl"


def test_resolve_release_assets_missing_wheel():
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            _make_asset("whisper-local-tui-darwin-arm64.tar.gz"),
            _make_asset("checksums.txt"),
            _make_asset("checksums.txt.asc"),
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="missing wheel"):
            upgrade.resolve_release_assets(target="darwin-arm64")


def test_resolve_release_assets_missing_tui():
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            _make_asset("whisper_local-1.0.0.whl"),
            _make_asset("checksums.txt"),
            _make_asset("checksums.txt.asc"),
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="missing TUI"):
            upgrade.resolve_release_assets(target="darwin-arm64")


def test_resolve_release_assets_missing_checksums():
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            _make_asset("whisper_local-1.0.0.whl"),
            _make_asset("whisper-local-tui-darwin-arm64.tar.gz"),
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="missing checksum manifest"):
            upgrade.resolve_release_assets(target="darwin-arm64")


def test_resolve_release_assets_missing_signature():
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            _make_asset("whisper_local-1.0.0.whl"),
            _make_asset("whisper-local-tui-darwin-arm64.tar.gz"),
            _make_asset("checksums.txt"),
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="missing checksum signature"):
            upgrade.resolve_release_assets(target="darwin-arm64")


def test_resolve_release_assets_with_version_tag():
    payload = {
        "tag_name": "v2.0.0",
        "assets": [
            _make_asset("whisper_local-2.0.0.whl", "https://example.com/whl"),
            _make_asset("whisper-local-tui-darwin-arm64.tar.gz", "https://example.com/tui"),
            _make_asset("checksums.txt", "https://example.com/checksums"),
            _make_asset("checksums.txt.asc", "https://example.com/sig"),
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        bundle = upgrade.resolve_release_assets(
            target="darwin-arm64", requested_version="2.0.0"
        )
    assert bundle.tag == "v2.0.0"


def test_resolve_release_assets_no_tag():
    payload = {"tag_name": "", "assets": []}
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="valid tag"):
            upgrade.resolve_release_assets(target="darwin-arm64")


def test_resolve_release_assets_multiple_wheels():
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            _make_asset("a.whl"),
            _make_asset("b.whl"),
            _make_asset("whisper-local-tui-darwin-arm64.tar.gz"),
            _make_asset("checksums.txt"),
            _make_asset("checksums.txt.asc"),
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="multiple wheel"):
            upgrade.resolve_release_assets(target="darwin-arm64")


# ---------------------------------------------------------------------------
# _verify_release_signature
# ---------------------------------------------------------------------------


def test_verify_release_signature_no_gpg(tmp_path: Path):
    with patch("whisper_local.upgrade.shutil.which", return_value=None):
        with pytest.raises(UpgradeError, match="gpg"):
            upgrade._verify_release_signature(
                repository="owner/repo",
                checksums_path=tmp_path / "checksums.txt",
                signature_path=tmp_path / "checksums.txt.asc",
            )


# ---------------------------------------------------------------------------
# _verify_downloaded_release_assets
# ---------------------------------------------------------------------------


def test_verify_downloaded_release_assets_checksum_mismatch(tmp_path: Path):
    bundle = ReleaseAssetBundle(
        repository="owner/repo",
        tag="v1.0.0",
        wheel_name="test.whl",
        wheel_url="https://example.com/whl",
        tui_name="tui.tar.gz",
        tui_url="https://example.com/tui",
        checksums_name="checksums.txt",
        checksums_url="https://example.com/checksums",
        signature_name="checksums.txt.asc",
        signature_url="https://example.com/sig",
        target="darwin-arm64",
    )
    # Bypass signature verification
    with patch("whisper_local.upgrade._verify_release_signature"):
        wheel_path = tmp_path / "test.whl"
        wheel_path.write_bytes(b"wheel content")
        tui_path = tmp_path / "tui.tar.gz"
        tui_path.write_bytes(b"tui content")

        checksums_path = tmp_path / "checksums.txt"
        wrong_digest = "0" * 64
        checksums_path.write_text(
            f"{wrong_digest}  test.whl\n{wrong_digest}  tui.tar.gz\n",
            encoding="utf-8",
        )
        sig_path = tmp_path / "checksums.txt.asc"
        sig_path.write_bytes(b"sig")

        with pytest.raises(UpgradeError, match="checksum mismatch"):
            upgrade._verify_downloaded_release_assets(
                bundle=bundle,
                checksums_path=checksums_path,
                signature_path=sig_path,
                wheel_path=wheel_path,
                tui_path=tui_path,
            )


def test_verify_downloaded_release_assets_success(tmp_path: Path):
    import hashlib
    wheel_path = tmp_path / "test.whl"
    wheel_path.write_bytes(b"wheel content")
    tui_path = tmp_path / "tui.tar.gz"
    tui_path.write_bytes(b"tui content")

    wheel_digest = hashlib.sha256(b"wheel content").hexdigest()
    tui_digest = hashlib.sha256(b"tui content").hexdigest()

    checksums_path = tmp_path / "checksums.txt"
    checksums_path.write_text(
        f"{wheel_digest}  test.whl\n{tui_digest}  tui.tar.gz\n",
        encoding="utf-8",
    )
    sig_path = tmp_path / "checksums.txt.asc"
    sig_path.write_bytes(b"sig")

    bundle = ReleaseAssetBundle(
        repository="owner/repo",
        tag="v1.0.0",
        wheel_name="test.whl",
        wheel_url="https://example.com/whl",
        tui_name="tui.tar.gz",
        tui_url="https://example.com/tui",
        checksums_name="checksums.txt",
        checksums_url="https://example.com/checksums",
        signature_name="checksums.txt.asc",
        signature_url="https://example.com/sig",
        target="darwin-arm64",
    )

    with patch("whisper_local.upgrade._verify_release_signature"):
        # Should not raise
        upgrade._verify_downloaded_release_assets(
            bundle=bundle,
            checksums_path=checksums_path,
            signature_path=sig_path,
            wheel_path=wheel_path,
            tui_path=tui_path,
        )


# ---------------------------------------------------------------------------
# normalize_version_tag — uncovered branches
# ---------------------------------------------------------------------------


def test_normalize_version_tag_empty_string():
    assert upgrade.normalize_version_tag("") is None


def test_normalize_version_tag_latest():
    assert upgrade.normalize_version_tag("latest") is None


def test_normalize_version_tag_with_v_prefix():
    assert upgrade.normalize_version_tag("v1.2.3") == "v1.2.3"


def test_normalize_version_tag_without_v_prefix():
    assert upgrade.normalize_version_tag("1.2.3") == "v1.2.3"


# ---------------------------------------------------------------------------
# _secure_temp_root
# ---------------------------------------------------------------------------


def test_secure_temp_root(tmp_path: Path):
    result = upgrade._secure_temp_root(tmp_path)
    assert result == tmp_path / ".tmp"
    assert result.exists()


def test_secure_temp_root_chmod_failure(tmp_path: Path):
    with patch.object(Path, "chmod", side_effect=OSError("not supported")):
        result = upgrade._secure_temp_root(tmp_path)
    assert result == tmp_path / ".tmp"


# ---------------------------------------------------------------------------
# detect_install_channel exception in is_relative_to
# ---------------------------------------------------------------------------


def test_detect_install_channel_exception_in_relative_to(tmp_path: Path):
    venv = tmp_path / "venv"
    venv.mkdir()
    exe = tmp_path / "bin" / "python"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/usr/bin/env python", encoding="utf-8")

    with patch.object(Path, "is_relative_to", side_effect=TypeError("fail")), \
         patch("whisper_local.upgrade._looks_like_homebrew_install", return_value=False):
        result = upgrade.detect_install_channel(
            executable=str(exe),
            installer_home=tmp_path,
        )
    assert result == "pip"


# ---------------------------------------------------------------------------
# read_install_manifest edge cases
# ---------------------------------------------------------------------------


def test_read_install_manifest_missing(tmp_path: Path):
    assert upgrade.read_install_manifest(tmp_path / "nonexistent.json") is None


def test_read_install_manifest_parse_error(tmp_path: Path):
    bad_json = tmp_path / "manifest.json"
    bad_json.write_text("not valid json{{{", encoding="utf-8")
    assert upgrade.read_install_manifest(bad_json) is None


# ---------------------------------------------------------------------------
# resolve_release_assets — fallback signature patterns
# ---------------------------------------------------------------------------


def test_resolve_release_assets_release_asc_signature():
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            _make_asset("whisper_local-1.0.0.whl", "https://example.com/whl"),
            _make_asset("whisper-local-tui-darwin-arm64.tar.gz", "https://example.com/tui"),
            _make_asset("checksums.txt", "https://example.com/checksums"),
            _make_asset("release.asc", "https://example.com/sig"),
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        bundle = upgrade.resolve_release_assets(target="darwin-arm64")
    assert bundle.signature_name == "release.asc"


def test_resolve_release_assets_checksum_asc_fallback():
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            _make_asset("whisper_local-1.0.0.whl", "https://example.com/whl"),
            _make_asset("whisper-local-tui-darwin-arm64.tar.gz", "https://example.com/tui"),
            _make_asset("checksums.txt", "https://example.com/checksums"),
            _make_asset("checksum-release.asc", "https://example.com/sig"),
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        bundle = upgrade.resolve_release_assets(target="darwin-arm64")
    assert "checksum" in bundle.signature_name.lower()


def test_resolve_release_assets_api_error():
    with patch("whisper_local.upgrade._github_get_json", side_effect=Exception("network error")):
        with pytest.raises(UpgradeError, match="Failed to fetch"):
            upgrade.resolve_release_assets(target="darwin-arm64")


def test_resolve_release_assets_invalid_assets_type():
    payload = {"tag_name": "v1.0.0", "assets": "not_a_list"}
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="invalid assets"):
            upgrade.resolve_release_assets(target="darwin-arm64")


def test_resolve_release_assets_missing_download_urls():
    payload = {
        "tag_name": "v1.0.0",
        "assets": [
            {"name": "test.whl", "browser_download_url": ""},
            {"name": "whisper-local-tui-darwin-arm64.tar.gz", "browser_download_url": "https://x.com/tui"},
            {"name": "checksums.txt", "browser_download_url": "https://x.com/cs"},
            {"name": "checksums.txt.asc", "browser_download_url": "https://x.com/sig"},
        ],
    }
    with patch("whisper_local.upgrade._github_get_json", return_value=payload):
        with pytest.raises(UpgradeError, match="missing download URLs"):
            upgrade.resolve_release_assets(target="darwin-arm64")


# ---------------------------------------------------------------------------
# _verify_release_signature — with gpg
# ---------------------------------------------------------------------------


def test_verify_release_signature_download_key_fails(tmp_path: Path):
    checksums = tmp_path / "checksums.txt"
    checksums.write_text("test")
    sig = tmp_path / "checksums.txt.asc"
    sig.write_text("sig")
    with patch("whisper_local.upgrade.shutil.which", return_value="/usr/bin/gpg"), \
         patch("whisper_local.upgrade._expected_signing_fingerprint", return_value="ABCD1234"), \
         patch("whisper_local.upgrade._signing_key_url_for_repository", return_value="https://example.com/key.gpg"), \
         patch("whisper_local.upgrade._download_to_file", side_effect=Exception("download failed")):
        with pytest.raises(UpgradeError, match="could not download signing key"):
            upgrade._verify_release_signature(
                repository="owner/repo",
                checksums_path=checksums,
                signature_path=sig,
                temp_dir_base=tmp_path,
            )


def test_verify_release_signature_fingerprint_mismatch(tmp_path: Path):
    checksums = tmp_path / "checksums.txt"
    checksums.write_text("test")
    sig = tmp_path / "checksums.txt.asc"
    sig.write_text("sig")

    def fake_run_cmd(cmd, **kwargs):
        if "--fingerprint" in cmd:
            return "fpr:::::::::WRONGFINGERPRINT1234:\n"
        return ""

    with patch("whisper_local.upgrade.shutil.which", return_value="/usr/bin/gpg"), \
         patch("whisper_local.upgrade._expected_signing_fingerprint", return_value="ABCDEF1234567890"), \
         patch("whisper_local.upgrade._signing_key_url_for_repository", return_value="https://example.com/key.gpg"), \
         patch("whisper_local.upgrade._download_to_file"), \
         patch("whisper_local.upgrade._run_command_or_error", side_effect=fake_run_cmd):
        with pytest.raises(UpgradeError, match="fingerprint was not found"):
            upgrade._verify_release_signature(
                repository="owner/repo",
                checksums_path=checksums,
                signature_path=sig,
                temp_dir_base=tmp_path,
            )


def test_verify_release_signature_success(tmp_path: Path):
    checksums = tmp_path / "checksums.txt"
    checksums.write_text("test")
    sig = tmp_path / "checksums.txt.asc"
    sig.write_text("sig")

    expected_fp = "ABCDEF1234567890"

    def fake_run_cmd(cmd, **kwargs):
        if "--fingerprint" in cmd:
            return f"fpr:::::::::{expected_fp}:\n"
        return ""

    with patch("whisper_local.upgrade.shutil.which", return_value="/usr/bin/gpg"), \
         patch("whisper_local.upgrade._expected_signing_fingerprint", return_value=expected_fp), \
         patch("whisper_local.upgrade._signing_key_url_for_repository", return_value="https://example.com/key.gpg"), \
         patch("whisper_local.upgrade._download_to_file"), \
         patch("whisper_local.upgrade._run_command_or_error", side_effect=fake_run_cmd):
        # Should not raise
        upgrade._verify_release_signature(
            repository="owner/repo",
            checksums_path=checksums,
            signature_path=sig,
            temp_dir_base=tmp_path,
        )


# ---------------------------------------------------------------------------
# _verify_downloaded_release_assets — tui mismatch
# ---------------------------------------------------------------------------


def test_verify_downloaded_release_assets_tui_mismatch(tmp_path: Path):
    import hashlib
    wheel_path = tmp_path / "test.whl"
    wheel_path.write_bytes(b"wheel content")
    tui_path = tmp_path / "tui.tar.gz"
    tui_path.write_bytes(b"tui content")

    wheel_digest = hashlib.sha256(b"wheel content").hexdigest()
    wrong_tui_digest = "0" * 64

    checksums_path = tmp_path / "checksums.txt"
    checksums_path.write_text(
        f"{wheel_digest}  test.whl\n{wrong_tui_digest}  tui.tar.gz\n",
        encoding="utf-8",
    )
    sig_path = tmp_path / "checksums.txt.asc"
    sig_path.write_bytes(b"sig")

    bundle = ReleaseAssetBundle(
        repository="owner/repo",
        tag="v1.0.0",
        wheel_name="test.whl",
        wheel_url="https://example.com/whl",
        tui_name="tui.tar.gz",
        tui_url="https://example.com/tui",
        checksums_name="checksums.txt",
        checksums_url="https://example.com/checksums",
        signature_name="checksums.txt.asc",
        signature_url="https://example.com/sig",
        target="darwin-arm64",
    )

    with patch("whisper_local.upgrade._verify_release_signature"):
        with pytest.raises(UpgradeError, match="TUI checksum mismatch"):
            upgrade._verify_downloaded_release_assets(
                bundle=bundle,
                checksums_path=checksums_path,
                signature_path=sig_path,
                wheel_path=wheel_path,
                tui_path=tui_path,
            )
