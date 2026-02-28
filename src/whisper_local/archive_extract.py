from __future__ import annotations

import os
import tarfile
from pathlib import Path, PurePosixPath
from typing import IO


MAX_ENTRIES = 1
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 8.0
_CHUNK_SIZE = 1024 * 1024


class ArchiveExtractionError(RuntimeError):
    pass


def _validate_expected_binary_name(expected_binary_name: str) -> None:
    if not expected_binary_name:
        raise ArchiveExtractionError("Expected binary name must be provided")


def _ensure_entry_limit(total_entries: int) -> None:
    if total_entries > MAX_ENTRIES:
        raise ArchiveExtractionError("TUI archive exceeded the maximum allowed number of entries")


def _is_unsafe_member_path(
    member_path: PurePosixPath,
    normalized_member_path: PurePosixPath,
) -> bool:
    return (
        member_path.is_absolute()
        or normalized_member_path.is_absolute()
        or ".." in member_path.parts
        or ".." in normalized_member_path.parts
    )


def _validate_member_path_safety(member_name: str) -> tuple[PurePosixPath, PurePosixPath]:
    member_path = PurePosixPath(member_name)
    normalized_member_path = PurePosixPath(member_name.replace("\\", "/"))
    if _is_unsafe_member_path(member_path, normalized_member_path):
        raise ArchiveExtractionError("TUI archive contained unsafe member paths")
    return member_path, normalized_member_path


def _validate_member_name_and_location(
    *,
    member_path: PurePosixPath,
    normalized_member_path: PurePosixPath,
    expected_binary_name: str,
) -> None:
    if member_path.name != expected_binary_name:
        raise ArchiveExtractionError(f"TUI archive entry must be named '{expected_binary_name}'")
    if (
        len(member_path.parts) != 1
        or len(normalized_member_path.parts) != 1
        or normalized_member_path.name != expected_binary_name
    ):
        raise ArchiveExtractionError("TUI archive entry must be a single root-level binary file")


def _validate_member_type_and_size(member: tarfile.TarInfo) -> None:
    if member.issym() or member.islnk():
        raise ArchiveExtractionError("TUI archive contained links, which are not allowed")
    if member.isdev() or member.isfifo():
        raise ArchiveExtractionError("TUI archive contained special files, which are not allowed")
    if not member.isfile():
        raise ArchiveExtractionError("TUI archive contained a non-regular entry, which is not allowed")
    if member.size < 0:
        raise ArchiveExtractionError("TUI archive contained a member with invalid size")
    if member.size == 0:
        raise ArchiveExtractionError("TUI archive contained a zero-byte executable entry")


def _update_and_validate_uncompressed_size(
    *,
    total_uncompressed_bytes: int,
    member_size: int,
    archive_size_bytes: int,
) -> int:
    updated_uncompressed_bytes = total_uncompressed_bytes + member_size
    if updated_uncompressed_bytes > MAX_UNCOMPRESSED_BYTES:
        raise ArchiveExtractionError("TUI archive exceeded the maximum allowed extracted size")
    if updated_uncompressed_bytes / archive_size_bytes > MAX_COMPRESSION_RATIO:
        raise ArchiveExtractionError("TUI archive exceeded the maximum allowed compression ratio")
    return updated_uncompressed_bytes


def _copy_member_stream_to_destination(
    *,
    extracted_stream: IO[bytes],
    output_handle: IO[bytes],
    expected_size: int,
) -> int:
    extracted_bytes = 0
    while extracted_bytes < expected_size:
        remaining_bytes = expected_size - extracted_bytes
        chunk = extracted_stream.read(min(_CHUNK_SIZE, remaining_bytes))
        if not chunk:
            break
        if len(chunk) > remaining_bytes:
            raise ArchiveExtractionError("TUI archive member exceeded declared metadata size")
        extracted_bytes += len(chunk)
        output_handle.write(chunk)
    return extracted_bytes


def _extract_member_to_staged_file(
    *,
    tar_handle: tarfile.TarFile,
    member: tarfile.TarInfo,
    staged_destination: Path,
) -> None:
    source_handle = tar_handle.extractfile(member)
    if source_handle is None:
        raise ArchiveExtractionError("TUI archive member could not be read")

    with source_handle as extracted_stream, staged_destination.open("wb") as output_handle:
        extracted_bytes = _copy_member_stream_to_destination(
            extracted_stream=extracted_stream,
            output_handle=output_handle,
            expected_size=member.size,
        )
        if extracted_stream.read(1):
            raise ArchiveExtractionError("TUI archive member exceeded declared metadata size")

    if extracted_bytes != member.size:
        raise ArchiveExtractionError("TUI archive member size did not match metadata")


def _cleanup_staged_destination(*, staged_destination: Path) -> None:
    if staged_destination.exists():
        staged_destination.unlink(missing_ok=True)


def _validate_extraction_completed(*, total_entries: int, extracted: bool) -> None:
    if total_entries == 0 or not extracted:
        raise ArchiveExtractionError("TUI archive did not contain an executable")


def _set_final_permissions(final_destination: Path) -> None:
    if not final_destination.name.endswith(".exe"):
        final_destination.chmod(0o755)


def install_tui_binary_from_archive(
    *,
    archive_path: Path,
    target_dir: Path,
    expected_binary_name: str,
) -> Path:
    _validate_expected_binary_name(expected_binary_name)

    archive_size_bytes = max(archive_path.stat().st_size, 1)
    target_dir.mkdir(parents=True, exist_ok=True)

    staged_destination = target_dir / f"{expected_binary_name}.tmp"
    final_destination = target_dir / expected_binary_name

    total_entries = 0
    total_uncompressed_bytes = 0
    extracted = False

    succeeded = False
    try:
        with tarfile.open(archive_path, "r:gz") as tar_handle:
            for member in tar_handle:
                total_entries += 1
                _ensure_entry_limit(total_entries)
                member_path, normalized_member_path = _validate_member_path_safety(member.name)
                _validate_member_type_and_size(member)
                total_uncompressed_bytes = _update_and_validate_uncompressed_size(
                    total_uncompressed_bytes=total_uncompressed_bytes,
                    member_size=member.size,
                    archive_size_bytes=archive_size_bytes,
                )
                _validate_member_name_and_location(
                    member_path=member_path,
                    normalized_member_path=normalized_member_path,
                    expected_binary_name=expected_binary_name,
                )
                _extract_member_to_staged_file(
                    tar_handle=tar_handle,
                    member=member,
                    staged_destination=staged_destination,
                )
                extracted = True
        succeeded = True
    except (tarfile.TarError, OSError) as exc:
        raise ArchiveExtractionError(f"Failed to open or read TUI archive: {exc}") from exc
    finally:
        if not succeeded:
            _cleanup_staged_destination(staged_destination=staged_destination)

    _validate_extraction_completed(total_entries=total_entries, extracted=extracted)

    os.replace(staged_destination, final_destination)
    _set_final_permissions(final_destination)
    return final_destination
