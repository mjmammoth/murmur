from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from whisper_local import archive_extract
from whisper_local.archive_extract import ArchiveExtractionError, install_tui_binary_from_archive


def _write_tar_gz_archive(archive_path: Path, entries: list[tuple[str, bytes]]) -> None:
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        for name, payload in entries:
            member = tarfile.TarInfo(name=name)
            member.size = len(payload)
            tar_handle.addfile(member, io.BytesIO(payload))


def test_install_tui_binary_from_archive_extracts_linux_binary(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    _write_tar_gz_archive(archive_path, [("whisper-local-tui", b"binary")])

    installed = install_tui_binary_from_archive(
        archive_path=archive_path,
        target_dir=target_dir,
        expected_binary_name="whisper-local-tui",
    )

    assert installed == target_dir / "whisper-local-tui"
    assert installed.read_bytes() == b"binary"


def test_install_tui_binary_from_archive_extracts_windows_binary(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "windows-x64"
    _write_tar_gz_archive(archive_path, [("whisper-local-tui.exe", b"binary")])

    installed = install_tui_binary_from_archive(
        archive_path=archive_path,
        target_dir=target_dir,
        expected_binary_name="whisper-local-tui.exe",
    )

    assert installed == target_dir / "whisper-local-tui.exe"
    assert installed.read_bytes() == b"binary"


def test_install_tui_binary_from_archive_rejects_extra_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    _write_tar_gz_archive(
        archive_path,
        [
            ("whisper-local-tui", b"binary"),
            ("extra.txt", b"extra"),
        ],
    )

    with pytest.raises(ArchiveExtractionError, match="maximum allowed number of entries"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )

    assert not (target_dir / "whisper-local-tui.tmp").exists(), "staged temp file should be cleaned up on error"


def test_install_tui_binary_from_archive_rejects_wrong_filename(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    _write_tar_gz_archive(archive_path, [("other-binary", b"binary")])

    with pytest.raises(ArchiveExtractionError, match="must be named 'whisper-local-tui'"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


@pytest.mark.parametrize("member_name", ["/etc/passwd", "../../etc/passwd", r"..\..\etc\passwd"])
def test_install_tui_binary_from_archive_rejects_unsafe_member_paths(
    tmp_path: Path,
    member_name: str,
) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    _write_tar_gz_archive(archive_path, [(member_name, b"unsafe")])

    with pytest.raises(ArchiveExtractionError, match="unsafe member paths"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_nested_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    _write_tar_gz_archive(archive_path, [("nested/whisper-local-tui", b"binary")])

    with pytest.raises(
        ArchiveExtractionError, match="entry must be a single root-level binary file"
    ):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_links(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        symlink = tarfile.TarInfo(name="whisper-local-tui")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = "/tmp/target"
        tar_handle.addfile(symlink)

    with pytest.raises(ArchiveExtractionError, match="links, which are not allowed"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_hardlinks(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        hardlink = tarfile.TarInfo(name="whisper-local-tui")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "target"
        tar_handle.addfile(hardlink)

    with pytest.raises(ArchiveExtractionError, match="links, which are not allowed"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_special_files(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        fifo_entry = tarfile.TarInfo(name="fifo-entry")
        fifo_entry.type = tarfile.FIFOTYPE
        tar_handle.addfile(fifo_entry)

    with pytest.raises(ArchiveExtractionError, match="special files, which are not allowed"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_device_files(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        char_device = tarfile.TarInfo(name="char-device")
        char_device.type = tarfile.CHRTYPE
        char_device.devmajor = 1
        char_device.devminor = 3
        tar_handle.addfile(char_device)

    with pytest.raises(ArchiveExtractionError, match="special files, which are not allowed"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_non_regular_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    with tarfile.open(archive_path, "w:gz") as tar_handle:
        directory = tarfile.TarInfo(name="whisper-local-tui")
        directory.type = tarfile.DIRTYPE
        tar_handle.addfile(directory)

    with pytest.raises(ArchiveExtractionError, match="non-regular entry"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_negative_member_size(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    archive_path.write_bytes(b"stub")
    target_dir = tmp_path / "tui" / "linux-x64"

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

    with patch("whisper_local.archive_extract.tarfile.open", return_value=tar_context):
        with pytest.raises(ArchiveExtractionError, match="member with invalid size"):
            install_tui_binary_from_archive(
                archive_path=archive_path,
                target_dir=target_dir,
                expected_binary_name="whisper-local-tui",
            )


def test_install_tui_binary_from_archive_rejects_zero_byte_executable(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    _write_tar_gz_archive(archive_path, [("whisper-local-tui", b"")])

    with pytest.raises(ArchiveExtractionError, match="zero-byte executable entry"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_large_uncompressed_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    _write_tar_gz_archive(archive_path, [("whisper-local-tui", b"binary")])
    monkeypatch.setattr(archive_extract, "MAX_UNCOMPRESSED_BYTES", 3)

    with pytest.raises(ArchiveExtractionError, match="maximum allowed extracted size"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_suspicious_compression_ratio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    target_dir = tmp_path / "tui" / "linux-x64"
    _write_tar_gz_archive(archive_path, [("whisper-local-tui", b"binary")])
    monkeypatch.setattr(archive_extract, "MAX_COMPRESSION_RATIO", 0.001)

    with pytest.raises(ArchiveExtractionError, match="maximum allowed compression ratio"):
        install_tui_binary_from_archive(
            archive_path=archive_path,
            target_dir=target_dir,
            expected_binary_name="whisper-local-tui",
        )


def test_install_tui_binary_from_archive_rejects_truncated_member_stream(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    archive_path.write_bytes(b"stub")
    target_dir = tmp_path / "tui" / "linux-x64"

    class TruncatedMember:
        name = "whisper-local-tui"
        size = 6

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
    tar_handle.__iter__.return_value = iter([TruncatedMember()])
    tar_handle.extractfile.return_value = io.BytesIO(b"abc")
    tar_context = MagicMock()
    tar_context.__enter__.return_value = tar_handle
    tar_context.__exit__.return_value = False

    with patch("whisper_local.archive_extract.tarfile.open", return_value=tar_context):
        with pytest.raises(ArchiveExtractionError, match="size did not match metadata"):
            install_tui_binary_from_archive(
                archive_path=archive_path,
                target_dir=target_dir,
                expected_binary_name="whisper-local-tui",
            )
    assert not (target_dir / "whisper-local-tui.tmp").exists()


def test_install_tui_binary_from_archive_rejects_oversized_member_stream(tmp_path: Path) -> None:
    archive_path = tmp_path / "tui.tar.gz"
    archive_path.write_bytes(b"stub")
    target_dir = tmp_path / "tui" / "linux-x64"

    class OversizedMember:
        name = "whisper-local-tui"
        size = 3

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
    tar_handle.__iter__.return_value = iter([OversizedMember()])
    tar_handle.extractfile.return_value = io.BytesIO(b"abcd")
    tar_context = MagicMock()
    tar_context.__enter__.return_value = tar_handle
    tar_context.__exit__.return_value = False

    with patch("whisper_local.archive_extract.tarfile.open", return_value=tar_context):
        with pytest.raises(ArchiveExtractionError, match="exceeded declared metadata size"):
            install_tui_binary_from_archive(
                archive_path=archive_path,
                target_dir=target_dir,
                expected_binary_name="whisper-local-tui",
            )
