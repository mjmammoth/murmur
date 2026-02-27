from __future__ import annotations

import os
import tarfile
from pathlib import Path, PurePosixPath


MAX_ENTRIES = 1
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 8.0
_CHUNK_SIZE = 1024 * 1024


class ArchiveExtractionError(RuntimeError):
    pass


def install_tui_binary_from_archive(
    *,
    archive_path: Path,
    target_dir: Path,
    expected_binary_name: str,
) -> Path:
    if not expected_binary_name:
        raise ArchiveExtractionError("Expected binary name must be provided")

    archive_size_bytes = max(archive_path.stat().st_size, 1)
    target_dir.mkdir(parents=True, exist_ok=True)

    staged_destination = target_dir / f"{expected_binary_name}.tmp"
    final_destination = target_dir / expected_binary_name

    total_entries = 0
    total_uncompressed_bytes = 0
    extracted = False

    try:
        with tarfile.open(archive_path, "r:gz") as tar_handle:
            for member in tar_handle:
                total_entries += 1
                if total_entries > MAX_ENTRIES:
                    raise ArchiveExtractionError(
                        "TUI archive exceeded the maximum allowed number of entries"
                    )

                member_path = PurePosixPath(member.name)
                normalized_member_path = PurePosixPath(member.name.replace("\\", "/"))
                if (
                    member_path.is_absolute()
                    or normalized_member_path.is_absolute()
                    or ".." in member_path.parts
                    or ".." in normalized_member_path.parts
                ):
                    raise ArchiveExtractionError("TUI archive contained unsafe member paths")
                if member.issym() or member.islnk():
                    raise ArchiveExtractionError("TUI archive contained links, which are not allowed")
                if member.isdev() or member.isfifo():
                    raise ArchiveExtractionError(
                        "TUI archive contained special files, which are not allowed"
                    )
                if not member.isfile():
                    raise ArchiveExtractionError(
                        "TUI archive contained a non-regular entry, which is not allowed"
                    )
                if member.size < 0:
                    raise ArchiveExtractionError("TUI archive contained a member with invalid size")
                if member.size == 0:
                    raise ArchiveExtractionError("TUI archive contained a zero-byte executable entry")

                total_uncompressed_bytes += member.size
                if total_uncompressed_bytes > MAX_UNCOMPRESSED_BYTES:
                    raise ArchiveExtractionError(
                        "TUI archive exceeded the maximum allowed extracted size"
                    )
                if total_uncompressed_bytes / archive_size_bytes > MAX_COMPRESSION_RATIO:
                    raise ArchiveExtractionError(
                        "TUI archive exceeded the maximum allowed compression ratio"
                    )

                if member_path.name != expected_binary_name:
                    raise ArchiveExtractionError(
                        f"TUI archive entry must be named '{expected_binary_name}'"
                    )
                if (
                    len(member_path.parts) != 1
                    or len(normalized_member_path.parts) != 1
                    or normalized_member_path.name != expected_binary_name
                ):
                    raise ArchiveExtractionError(
                        "TUI archive entry must be a single root-level binary file"
                    )

                source_handle = tar_handle.extractfile(member)
                if source_handle is None:
                    raise ArchiveExtractionError("TUI archive member could not be read")

                with source_handle as extracted_stream, staged_destination.open("wb") as output_handle:
                    extracted_bytes = 0
                    while extracted_bytes < member.size:
                        remaining_bytes = member.size - extracted_bytes
                        chunk = extracted_stream.read(min(_CHUNK_SIZE, remaining_bytes))
                        if not chunk:
                            break
                        if len(chunk) > remaining_bytes:
                            raise ArchiveExtractionError(
                                "TUI archive member exceeded declared metadata size"
                            )
                        extracted_bytes += len(chunk)
                        output_handle.write(chunk)
                    if extracted_stream.read(1):
                        raise ArchiveExtractionError(
                            "TUI archive member exceeded declared metadata size"
                        )
                if extracted_bytes != member.size:
                    raise ArchiveExtractionError("TUI archive member size did not match metadata")
                extracted = True
    except (tarfile.TarError, OSError) as exc:
        raise ArchiveExtractionError(f"Failed to open or read TUI archive: {exc}") from exc
    finally:
        if not extracted and staged_destination.exists():
            staged_destination.unlink(missing_ok=True)

    if total_entries == 0 or not extracted:
        raise ArchiveExtractionError("TUI archive did not contain an executable")

    os.replace(staged_destination, final_destination)
    if not final_destination.name.endswith(".exe"):
        final_destination.chmod(0o755)
    return final_destination
