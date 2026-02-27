from __future__ import annotations

import io
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

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


def _write_tar_gz_archive(archive_path: Path, entries: list[tuple[str, bytes]]) -> None:
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        for name, payload in entries:
            member = tarfile.TarInfo(name=name)
            member.size = len(payload)
            tar_handle.addfile(member, io.BytesIO(payload))


def test_replace_tui_binary_extracts_expected_binary(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    _write_tar_gz_archive(archive_path, [("whisper-local-tui", b"binary")])

    upgrade._replace_tui_binary(
        app_home=app_home,
        target="linux-x64",
        archive_path=archive_path,
    )

    installed_binary = app_home / "tui" / "linux-x64" / "whisper-local-tui"
    assert installed_binary.read_bytes() == b"binary"


def test_replace_tui_binary_rejects_too_many_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    _write_tar_gz_archive(
        archive_path,
        [
            ("whisper-local-tui", b"binary"),
            ("extra.txt", b"extra"),
        ],
    )
    monkeypatch.setattr(upgrade, "MAX_TUI_ARCHIVE_ENTRIES", 1)

    with pytest.raises(UpgradeError, match="maximum allowed number of entries"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


def test_replace_tui_binary_rejects_large_uncompressed_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    _write_tar_gz_archive(archive_path, [("whisper-local-tui", b"binary")])
    monkeypatch.setattr(upgrade, "MAX_TUI_ARCHIVE_UNCOMPRESSED_BYTES", 3)

    with pytest.raises(UpgradeError, match="maximum allowed extracted size"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


def test_replace_tui_binary_rejects_suspicious_compression_ratio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    _write_tar_gz_archive(archive_path, [("whisper-local-tui", b"binary")])
    monkeypatch.setattr(upgrade, "MAX_TUI_ARCHIVE_COMPRESSION_RATIO", 0.001)

    with pytest.raises(UpgradeError, match="maximum allowed compression ratio"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


@pytest.mark.parametrize("member_name", ["/etc/passwd", "../../etc/passwd", r"..\..\etc\passwd"])
def test_replace_tui_binary_rejects_unsafe_member_paths(tmp_path: Path, member_name: str) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    _write_tar_gz_archive(archive_path, [(member_name, b"unsafe")])

    with pytest.raises(UpgradeError, match="unsafe member paths"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


def test_replace_tui_binary_rejects_links(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        symlink = tarfile.TarInfo(name="whisper-local-tui")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = "/tmp/target"
        tar_handle.addfile(symlink)

    with pytest.raises(UpgradeError, match="links, which are not allowed"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


def test_replace_tui_binary_rejects_hardlinks(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        hardlink = tarfile.TarInfo(name="whisper-local-tui")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "target"
        tar_handle.addfile(hardlink)

    with pytest.raises(UpgradeError, match="links, which are not allowed"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


def test_replace_tui_binary_rejects_special_files(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        fifo_entry = tarfile.TarInfo(name="fifo-entry")
        fifo_entry.type = tarfile.FIFOTYPE
        tar_handle.addfile(fifo_entry)

    with pytest.raises(UpgradeError, match="special files, which are not allowed"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


def test_replace_tui_binary_rejects_device_files(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        char_device = tarfile.TarInfo(name="char-device")
        char_device.type = tarfile.CHRTYPE
        char_device.devmajor = 1
        char_device.devminor = 3
        tar_handle.addfile(char_device)

    with pytest.raises(UpgradeError, match="special files, which are not allowed"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


def test_replace_tui_binary_rejects_negative_member_size(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    archive_path.write_bytes(b"stub")

    class NegativeSizeMember:
        name = "whisper-local-tui"
        size = -1

        def issym(self) -> bool:
            return False

        def islnk(self) -> bool:
            return False

        def isdev(self) -> bool:
            return False

        def isfifo(self) -> bool:
            return False

        def isfile(self) -> bool:
            return True

    tar_handle = MagicMock()
    tar_handle.__iter__.return_value = iter([NegativeSizeMember()])
    tar_context = MagicMock()
    tar_context.__enter__.return_value = tar_handle
    tar_context.__exit__.return_value = False

    with patch("whisper_local.upgrade.tarfile.open", return_value=tar_context):
        with pytest.raises(UpgradeError, match="member with invalid size"):
            upgrade._replace_tui_binary(
                app_home=app_home,
                target="linux-x64",
                archive_path=archive_path,
            )


def test_replace_tui_binary_raises_when_no_executable_candidate_exists(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    _write_tar_gz_archive(archive_path, [("README.txt", b"text only")])

    with pytest.raises(UpgradeError, match="did not contain an executable"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


def test_replace_tui_binary_rejects_zero_byte_executable(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    archive_path = tmp_path / "tui.tar.gz"
    _write_tar_gz_archive(archive_path, [("whisper-local-tui", b"")])

    with pytest.raises(UpgradeError, match="zero-byte executable entry"):
        upgrade._replace_tui_binary(
            app_home=app_home,
            target="linux-x64",
            archive_path=archive_path,
        )


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
