from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Literal, Sized, cast

# Set before importing huggingface_hub so it applies reliably.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from huggingface_hub import HfApi, hf_hub_download, snapshot_download

from murmur import config as config_module
from murmur.config import RUNTIME_FASTER_WHISPER, RUNTIME_WHISPER_CPP
from murmur.model_ops import ModelRuntimeOperations, get_model_runtime_operations_factory


logger = logging.getLogger(__name__)

RuntimeName = Literal["faster-whisper", "whisper.cpp"]
RUNTIME_NAMES: tuple[RuntimeName, RuntimeName] = (RUNTIME_FASTER_WHISPER, RUNTIME_WHISPER_CPP)
RUNTIME_FORMATS: dict[RuntimeName, str] = {
    RUNTIME_FASTER_WHISPER: "ctranslate2",
    RUNTIME_WHISPER_CPP: "ggml",
}

MODEL_NAMES = ["tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo"]
MODEL_REPO_IDS: dict[str, str] = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "dropbox-dash/faster-whisper-large-v3-turbo",
}
MODEL_REPO_ALIASES: dict[str, tuple[str, ...]] = {
    # Legacy location used by older app versions.
    "large-v3-turbo": ("Systran/faster-whisper-large-v3-turbo",),
}

WHISPER_CPP_REPO_ID = "ggerganov/whisper.cpp"
WHISPER_CPP_MODEL_FILES: dict[str, str] = {
    "tiny": "ggml-tiny.bin",
    "base": "ggml-base.bin",
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin",
    "large-v2": "ggml-large-v2.bin",
    "large-v3": "ggml-large-v3.bin",
    "large-v3-turbo": "ggml-large-v3-turbo.bin",
}

MODEL_REQUIRED_FILES = (
    "model.bin",
    "config.json",
    "tokenizer.json",
)
MODEL_REQUIRED_FILE_ALTERNATIVES = (
    ("vocabulary.json", "vocabulary.txt"),
)
# Fallback display sizes when remote metadata is unavailable.
# Values are approximate and may vary slightly by repository revision.
MODEL_ESTIMATED_SIZE_BYTES: dict[str, int] = {
    "tiny": 80 * 1024 * 1024,
    "base": 150 * 1024 * 1024,
    "small": 500 * 1024 * 1024,
    "medium": 1600 * 1024 * 1024,
    "large-v2": 3200 * 1024 * 1024,
    "large-v3": 3200 * 1024 * 1024,
    "large-v3-turbo": 1600 * 1024 * 1024,
}
WHISPER_CPP_ESTIMATED_SIZE_BYTES: dict[str, int] = {
    "tiny": 75 * 1024 * 1024,
    "base": 145 * 1024 * 1024,
    "small": 485 * 1024 * 1024,
    "medium": 1500 * 1024 * 1024,
    "large-v2": 3000 * 1024 * 1024,
    "large-v3": 3000 * 1024 * 1024,
    "large-v3-turbo": 1500 * 1024 * 1024,
}
_MODEL_SIZE_CACHE: dict[str, int] = {}
_MODEL_SIZE_CACHE_LOCK = threading.Lock()


class DownloadCancelledError(RuntimeError):
    """Raised when a model download is cancelled by shutdown."""

    def __init__(self, message: str = "Download cancelled") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class ModelVariantInfo:
    runtime: RuntimeName
    format: str
    installed: bool
    path: Path | None = None
    size_bytes: int | None = None
    size_estimated: bool = False


@dataclass(frozen=True)
class ModelInfo:
    name: str
    variants: dict[RuntimeName, ModelVariantInfo]


def get_hf_cache_dir() -> Path:
    """
    Determine the directory used for Hugging Face cache files.

    Checks environment variables in order of precedence: HF_HOME, XDG_CACHE_HOME (appending "huggingface"), and falls back to "~/.cache/huggingface".

    Returns:
        Path: Path to the resolved Hugging Face cache directory.
    """
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home)
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "huggingface"
    return Path("~/.cache/huggingface").expanduser()


def normalize_model_runtime(runtime: str | None) -> RuntimeName:
    """
    Normalize a runtime identifier to one of the supported RuntimeName values.

    Returns:
        'whisper.cpp' if the given runtime normalizes to "whisper.cpp", otherwise 'faster-whisper'.
    """
    normalized = config_module.normalize_runtime_name(str(runtime or "faster-whisper"))
    if normalized == RUNTIME_WHISPER_CPP:
        return RUNTIME_WHISPER_CPP
    return RUNTIME_FASTER_WHISPER


def _model_operations_for_runtime(runtime: str | None) -> ModelRuntimeOperations:
    """
    Return the model runtime operations implementation corresponding to the given runtime.

    Parameters:
        runtime (str | None): Runtime identifier (e.g., "faster-whisper" or "whisper.cpp"). If None, the runtime is normalized to the default.

    Returns:
        An object that implements model operations for the resolved runtime.
    """
    normalized = normalize_model_runtime(runtime)
    return get_model_runtime_operations_factory().for_runtime(normalized)


def model_variant_format(runtime: str | None) -> str:
    """
    Get the model file format string for a given runtime.

    Parameters:
        runtime: The runtime name ("faster-whisper", "whisper.cpp") or None to use the default runtime.

    Returns:
        The format string associated with the normalized runtime (for example, "ctranslate2" or "ggml").
    """
    return RUNTIME_FORMATS[normalize_model_runtime(runtime)]


def _size_cache_key(model_name: str, runtime: str | None = None) -> str:
    """
    Builds a cache key that uniquely identifies a model variant for a runtime.

    Parameters:
        model_name (str): The model identifier (e.g., "tiny", "base").
        runtime (str | None): Runtime name to normalize (defaults to the module's default runtime).

    Returns:
        str: Cache key in the form "<runtime>:<model_name>" where <runtime> is the normalized runtime name.
    """
    return f"{normalize_model_runtime(runtime)}:{model_name}"


def _model_cache_path(model_name: str) -> Path:
    """
    Return the primary Hugging Face hub cache directory path for the given model.

    Parameters:
        model_name (str): Model identifier as listed in the module's supported models.

    Returns:
        Path: Path to the primary cache directory for the model.
    """
    return _model_cache_paths(model_name)[0]


def _cache_path_for_repo_id(repo_id: str) -> Path:
    """
    Map a Hugging Face repository id to its local hub cache directory.

    Parameters:
        repo_id (str): Repository identifier in the form "owner/model".

    Returns:
        Path: Path to the model cache directory inside the Hugging Face hub cache (e.g., ~/.cache/huggingface/hub/models--owner--model).
    """
    cache_name = f"models--{repo_id.replace('/', '--')}"
    return get_hf_cache_dir() / "hub" / cache_name


def murmur_model_cache_paths() -> tuple[Path, ...]:
    """
    Return all Hugging Face cache directories managed by murmur model operations.

    Includes faster-whisper model repositories (primary + aliases) and the whisper.cpp
    repository cache root. Paths are deduplicated while preserving order.
    """
    paths: list[Path] = []
    for model_name in MODEL_NAMES:
        paths.extend(_model_cache_paths(model_name))
    paths.append(_cache_path_for_repo_id(WHISPER_CPP_REPO_ID))

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser().resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return tuple(deduped)


def _whisper_cpp_snapshots_dir() -> Path:
    """
    Locate the snapshots directory for the whisper.cpp repository inside the local Hugging Face cache.

    Returns:
        Path: Path to the whisper.cpp repository's snapshots directory (the path may not exist on disk).
    """
    return _cache_path_for_repo_id(WHISPER_CPP_REPO_ID) / "snapshots"


def whisper_cpp_model_filename(model_name: str) -> str:
    """
    Return the expected whisper.cpp binary filename for a supported model.

    Parameters:
        model_name (str): Model identifier; must be one of the supported MODEL_NAMES.

    Returns:
        str: The whisper.cpp filename corresponding to `model_name`.

    Raises:
        ValueError: If `model_name` is not a known model.
        RuntimeError: If a filename mapping for `model_name` is missing.
    """
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")
    filename = WHISPER_CPP_MODEL_FILES.get(model_name)
    if not filename:
        raise RuntimeError(f"whisper.cpp model file mapping missing for model: {model_name}")
    return filename


def _find_cached_whisper_cpp_model(filename: str) -> Path | None:
    """
    Locate the most recently modified cached whisper.cpp model file with the given filename.

    Searches the whisper.cpp snapshots directory for files named `filename`, ignores non-directory entries, and returns the newest matching file path.

    Parameters:
        filename (str): The model filename to search for within cached whisper.cpp snapshots.

    Returns:
        Path | None: `Path` to the most recently modified matching file, or `None` if no matching cached file is found.
    """
    snapshots = _whisper_cpp_snapshots_dir()
    if not snapshots.exists():
        return None

    candidates: list[Path] = []
    for snapshot in snapshots.iterdir():
        if not snapshot.is_dir():
            continue
        candidate = snapshot / filename
        if candidate.exists() and candidate.is_file():
            candidates.append(candidate)

    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _model_repo_ids(model_name: str) -> tuple[str, ...]:
    """
    Get repository IDs for a model with the primary repository listed first.

    Parameters:
        model_name (str): Supported model name.

    Returns:
        repo_ids (tuple[str, ...]): Tuple containing the primary repo ID followed by any alias repo IDs.

    Raises:
        ValueError: If `model_name` is not a known/supported model.
    """
    primary_repo = _model_repo_id(model_name)
    aliases = MODEL_REPO_ALIASES.get(model_name, ())
    return (primary_repo, *aliases)


def _model_cache_paths(model_name: str) -> tuple[Path, ...]:
    """
    Get all cache directory paths that may contain snapshots for the given model.

    Parameters:
        model_name (str): Supported model name.

    Returns:
        tuple[Path, ...]: Paths for each repository ID associated with the model, with the primary repository first followed by any aliases.
    """
    return tuple(_cache_path_for_repo_id(repo_id) for repo_id in _model_repo_ids(model_name))


def _model_repo_id(model_name: str) -> str:
    """
    Resolve the primary Hugging Face repository identifier for a model name.

    Parameters:
        model_name (str): Supported model name.

    Returns:
        str: Primary repository identifier associated with the model.

    Raises:
        ValueError: If `model_name` is not a recognized supported model.
    """
    repo_id = MODEL_REPO_IDS.get(model_name)
    if not repo_id:
        raise ValueError(f"Unknown model: {model_name}")
    return repo_id


def is_model_installed(model_name: str, runtime: str | None = "faster-whisper") -> bool:
    """
    Check whether the specified model variant is installed for the given runtime.

    If the model name is not one of the supported models, this returns `false`.

    Parameters:
        runtime (str | None): Runtime identifier to check (e.g., "faster-whisper" or "whisper.cpp"); `None` or unknown values are normalized to the default runtime.

    Returns:
        `true` if the model variant is installed, `false` otherwise.
    """
    if model_name not in MODEL_NAMES:
        return False
    return get_installed_model_path(model_name, runtime=runtime) is not None


def is_model_variant_installed(model_name: str, runtime: str | None) -> bool:
    """
    Check whether the specified model variant for a given runtime is installed.

    Parameters:
        model_name (str): Name of the model (e.g., "tiny", "base", "small", "medium", "large-v2").
        runtime (str | None): Runtime name ("faster-whisper" or "whisper.cpp") or None to use the default.

    Returns:
        `True` if the model variant for the given runtime is installed, `False` otherwise.
    """
    return is_model_installed(model_name, runtime=runtime)


def _get_installed_faster_model_path(model_name: str) -> Path | None:
    """
    Locate the most recently modified complete cache snapshot for a faster-whisper model.

    Parameters:
        model_name (str): Supported model identifier (one of MODEL_NAMES).

    Returns:
        Path | None: Path to the newest complete snapshot directory for the model, or `None` if the model is unknown or no complete snapshots are found.
    """
    if model_name not in MODEL_NAMES:
        return None
    candidates: list[Path] = []
    for cache_path in _model_cache_paths(model_name):
        for snapshot_path in _iter_snapshot_paths(cache_path):
            if _snapshot_is_complete(snapshot_path):
                candidates.append(snapshot_path)
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def get_installed_whisper_cpp_model_path(model_name: str) -> Path | None:
    """
    Locate the locally cached whisper.cpp model file for a supported model name.

    Parameters:
        model_name (str): One of the supported model identifiers (e.g., "tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo").

    Returns:
        Path | None: Path to the most recently cached whisper.cpp model file if present, `None` if the model name is unsupported or no cached file is found.
    """
    if model_name not in MODEL_NAMES:
        return None
    return _find_cached_whisper_cpp_model(whisper_cpp_model_filename(model_name))


def get_installed_model_path(
    model_name: str, runtime: str | None = "faster-whisper"
) -> Path | None:
    """
    Locate the most recently installed model path for a model/runtime combination.

    Parameters:
        model_name (str): Model name to resolve.
        runtime (str | None): Runtime identifier.

    Returns:
        Path | None: Installed path or None when missing.
    """
    if model_name not in MODEL_NAMES:
        return None
    operations = _model_operations_for_runtime(runtime)
    return operations.installed_path(model_name)


def _cache_path_size_bytes(cache_path: Path) -> int:
    """
    Compute the total size in bytes of all regular files under a cache directory.

    Parameters:
        cache_path (Path): Directory whose file sizes will be summed.

    Returns:
        int: Sum of sizes in bytes of all regular files under `cache_path`. Returns 0 if `cache_path` does not exist.
    """
    if not cache_path.exists():
        return 0
    total = 0
    for path in cache_path.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _iter_snapshot_paths(cache_path: Path) -> list[Path]:
    """
    List immediate snapshot subdirectories under a repository cache's "snapshots" folder.

    Parameters:
        cache_path (Path): Path to the repository cache directory that may contain a "snapshots" subdirectory.

    Returns:
        List[Path]: Paths for each immediate subdirectory inside cache_path/"snapshots"; an empty list if the snapshots directory does not exist.
    """
    snapshots_path = cache_path / "snapshots"
    if not snapshots_path.exists():
        return []
    return [path for path in snapshots_path.iterdir() if path.is_dir()]


def _snapshot_is_complete(snapshot_path: Path) -> bool:
    """
    Determine whether a model snapshot directory is complete.

    A snapshot is complete when every filename listed in MODEL_REQUIRED_FILES exists in the directory and has size greater than zero, and for each tuple in MODEL_REQUIRED_FILE_ALTERNATIVES at least one listed file exists and has size greater than zero.

    Parameters:
        snapshot_path (Path): Path to the candidate snapshot directory to validate.

    Returns:
        bool: `True` if the snapshot meets the completeness criteria described above, `False` otherwise.
    """
    def has_nonempty_file(filename: str) -> bool:
        """
        Check whether a given file exists under the current snapshot_path and has a size greater than zero.

        Parameters:
            filename (str): Name (or relative path) of the file to check within the module's snapshot_path.

        Returns:
            bool: `true` if the file exists at snapshot_path/filename and its size is greater than zero, `false` otherwise.
        """
        candidate = snapshot_path / filename
        if not candidate.is_file():
            return False
        try:
            return candidate.stat().st_size > 0
        except OSError:
            return False

    for filename in MODEL_REQUIRED_FILES:
        if not has_nonempty_file(filename):
            return False

    for candidate_group in MODEL_REQUIRED_FILE_ALTERNATIVES:
        if not any(has_nonempty_file(filename) for filename in candidate_group):
            return False

    return True


def _prune_incomplete_snapshots(cache_path: Path) -> bool:
    """Remove incomplete snapshot directories. Returns True if any were removed."""
    removed = False
    for snapshot_path in _iter_snapshot_paths(cache_path):
        if _snapshot_is_complete(snapshot_path):
            continue
        try:
            shutil.rmtree(snapshot_path)
            removed = True
        except Exception:
            logger.warning("Failed to remove incomplete model snapshot: %s", snapshot_path)
    return removed


def _prune_incomplete_blobs(cache_path: Path) -> bool:
    """Remove .incomplete files under cache_path/blobs. Returns True if any were removed."""
    removed = False
    blobs_path = cache_path / "blobs"
    if blobs_path.exists():
        for partial_path in blobs_path.glob("*.incomplete"):
            try:
                partial_path.unlink()
                removed = True
            except Exception:
                logger.warning("Failed to remove partial model blob: %s", partial_path)
    return removed


def _remove_empty_cache(cache_path: Path) -> None:
    """Remove cache_path entirely if no snapshot directories remain."""
    snapshots_path = cache_path / "snapshots"
    try:
        has_snapshots = snapshots_path.exists() and any(
            path.is_dir() for path in snapshots_path.iterdir()
        )
    except Exception:
        has_snapshots = True
    if has_snapshots:
        return
    try:
        shutil.rmtree(cache_path)
    except Exception:
        logger.warning("Failed to remove empty model cache path: %s", cache_path)


def _prune_cache_path(cache_path: Path) -> None:
    """
    Remove incomplete model snapshot data and orphaned partial blobs from a model cache path.

    Prunes any snapshot directories under `cache_path` that are not complete, removes `.incomplete` files under `cache_path/blobs`, and if the cache contains no remaining snapshot directories removes the entire `cache_path`. Failures to remove individual files or directories are logged but do not raise.
    """
    _prune_incomplete_snapshots(cache_path)
    _prune_incomplete_blobs(cache_path)
    _remove_empty_cache(cache_path)


def _prune_whisper_cpp_cache() -> None:
    """
    Remove orphaned partial download blobs for the whisper.cpp model cache.

    This function deletes files with the ".incomplete" suffix from the whisper.cpp repository cache "blobs" directory; if the blobs directory does not exist the call is a no-op. Failures to remove individual files are logged as warnings.
    """
    cache_path = _cache_path_for_repo_id(WHISPER_CPP_REPO_ID)
    blobs_path = cache_path / "blobs"
    if blobs_path.exists():
        for partial_path in blobs_path.glob("*.incomplete"):
            try:
                partial_path.unlink()
            except Exception:
                logger.warning("Failed to remove partial whisper.cpp blob: %s", partial_path)


def prune_invalid_model_cache(model_name: str) -> None:
    """
    Remove incomplete or invalid cached snapshots and orphaned blobs for a model.

    For each possible cache path for the given model, removes partial or incomplete snapshot
    directories and cleans up orphaned blobs; if the model name is not recognized, this is a no-op.

    Parameters:
        model_name (str): Supported model identifier to prune. Unknown model names are ignored.
    """
    if model_name not in MODEL_NAMES:
        return
    for cache_path in _model_cache_paths(model_name):
        if cache_path.exists():
            _prune_cache_path(cache_path)
    _prune_whisper_cpp_cache()


def prune_invalid_model_caches() -> None:
    """
    Prune incomplete or invalid cache snapshots for all configured models.

    Removes incomplete snapshots, partial blobs, and empty cache directories for every model known to the application.
    """
    for model_name in MODEL_NAMES:
        prune_invalid_model_cache(model_name)


def _faster_model_cache_size_bytes(model_name: str) -> int:
    """
    Return the total size in bytes of all cached snapshots for the given model across configured cache paths.

    Parameters:
        model_name (str): Model identifier.

    Returns:
        int: Sum of sizes (in bytes) of all files under the model's cache paths; 0 if no cache is present.
    """
    total = 0
    for cache_path in _model_cache_paths(model_name):
        total += _cache_path_size_bytes(cache_path)
    return total


def _whisper_cpp_model_cache_size_bytes(model_name: str) -> int:
    """
    Get the file size in bytes of the installed whisper.cpp model file.

    Returns:
    	The size in bytes of the model file, or 0 if the model is not installed or the file cannot be accessed.
    """
    path = get_installed_whisper_cpp_model_path(model_name)
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def model_cache_size_bytes(
    model_name: str, runtime: str | None = "faster-whisper"
) -> int:
    """
    Get total size in bytes of the local cache for a model variant.

    Parameters:
        model_name (str): Supported model identifier (e.g., "tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo").
        runtime (str | None): Runtime identifier (e.g., "faster-whisper" or "whisper.cpp"). Defaults to "faster-whisper".

    Returns:
        int: Total size in bytes of cached files for the specified model and runtime; `0` if the model or runtime is unknown or no cached files are present.
    """
    if model_name not in MODEL_NAMES:
        return 0
    operations = _model_operations_for_runtime(runtime)
    return operations.cache_size_bytes(model_name)


def list_available_models() -> list[str]:
    """
    List supported model names available for download or selection.

    Returns:
        list[str]: A list of supported model name strings.
    """
    return list(MODEL_NAMES)


def list_installed_models() -> list[ModelInfo]:
    """
    Retrieve information about all supported models and their runtime-specific variants.

    Returns:
        models (list[ModelInfo]): A list of ModelInfo objects, one per supported model. Each ModelInfo.variants maps a runtime name to a ModelVariantInfo describing that variant's runtime, file format, whether it is installed, the installed path (or None), the resolved size in bytes (exact or estimated, or None), and whether the reported size is an estimate.
    """
    models: list[ModelInfo] = []
    for name in MODEL_NAMES:
        variants: dict[RuntimeName, ModelVariantInfo] = {}
        for runtime in RUNTIME_NAMES:
            operations = _model_operations_for_runtime(runtime)
            installed_path = operations.installed_path(name)
            with _MODEL_SIZE_CACHE_LOCK:
                exact_size = _MODEL_SIZE_CACHE.get(_size_cache_key(name, runtime))
            estimated_size = operations.estimated_size_bytes(name)
            size_bytes = exact_size if exact_size is not None else estimated_size
            variants[runtime] = ModelVariantInfo(
                runtime=runtime,
                format=RUNTIME_FORMATS[runtime],
                installed=installed_path is not None,
                path=installed_path,
                size_bytes=size_bytes,
                size_estimated=exact_size is None and size_bytes is not None,
            )
        models.append(ModelInfo(name=name, variants=variants))
    return models


def _resolve_repo_total_bytes(repo_id: str) -> int | None:
    """
    Estimate total size in bytes of all files in a Hugging Face model repository.

    Fetches the repository's file metadata and sums sizes reported as positive integers; returns `None` if metadata cannot be retrieved or contains no positive sizes.

    Returns:
        int | None: Total size in bytes, or `None` if unavailable.
    """
    try:
        info = HfApi().model_info(repo_id=repo_id, files_metadata=True)
    except Exception as exc:
        logger.debug("Unable to fetch size metadata for %s: %s", repo_id, exc)
        return None

    total = 0
    for sibling in getattr(info, "siblings", []) or []:
        size = getattr(sibling, "size", None)
        if isinstance(size, int) and size > 0:
            total += size
    return total or None


def _resolve_repo_file_size_bytes(repo_id: str, filename: str) -> int | None:
    """
    Return the byte size of a specific file in a Hugging Face repository if available.

    Queries the repository metadata and returns the positive size of the named file when present.

    Returns:
        int | None: Positive file size in bytes if found, `None` if not found or on error.
    """
    try:
        info = HfApi().model_info(repo_id=repo_id, files_metadata=True)
    except Exception as exc:
        logger.debug("Unable to fetch file size metadata for %s/%s: %s", repo_id, filename, exc)
        return None

    for sibling in getattr(info, "siblings", []) or []:
        sibling_name = str(getattr(sibling, "rfilename", "") or "")
        if sibling_name != filename:
            continue
        size = getattr(sibling, "size", None)
        if isinstance(size, int) and size > 0:
            return size
        break
    return None


def _coerce_tqdm_float(value: object) -> float:
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return 0.0


def _is_download_bytes_bar(kwargs: dict[str, object]) -> bool:
    name = str(kwargs.get("name", ""))
    unit = str(kwargs.get("unit", "")).upper()
    return name == "huggingface_hub.snapshot_download" or unit == "B"


def _check_download_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise DownloadCancelledError("Download cancelled during shutdown")


def _make_progress_tqdm(
    callback: Callable[[int], None],
    expected_total_bytes: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> type[Any]:
    """
    Create a tqdm-compatible progress class that reports download progress via the provided callback.

    The returned class can be used in two modes by callers that expect a tqdm-like object:
    1. As an iterable wrapper (e.g., `for f in tqdm_class(files):`) to iterate file lists.
    2. As a byte-level progress bar for file download progress (uses `update(n)` and `total`).

    Parameters:
        callback (Callable[[int], None]): Function called with the current completion percent (0-100) when progress changes.
        expected_total_bytes (int | None): Optional expected total byte size used to compute percent when per-file totals are unavailable.
        cancel_check (Callable[[], bool] | None): Optional callable checked at key points; if it returns `True`, a DownloadCancelledError is raised.

    Returns:
        type: A tqdm-like class whose instances emit integer percent complete to `callback` and support common tqdm methods used by download routines.

    Raises:
        DownloadCancelledError: If `cancel_check` returns `True` during an operation.
    """

    _outer_expected_total_bytes = float(expected_total_bytes or 0)

    class _ProgressTqdm:
        _lock: threading.Lock = threading.Lock()

        def __init__(
            self,
            iterable: Iterable[Any] | None = None,
            *args: object,
            **kwargs: object,
        ) -> None:
            del args
            _check_download_cancelled(cancel_check)
            self._iterable = iterable
            self.total = _coerce_tqdm_float(kwargs.get("total", 0) or 0)
            self.n = _coerce_tqdm_float(kwargs.get("initial", 0) or 0)
            self.disable = bool(kwargs.get("disable", False))
            self._expected_total_bytes = _outer_expected_total_bytes
            self._is_download_bytes_bar = _is_download_bytes_bar(kwargs)
            self._last_percent = -1
            self._emit_if_bytes_bar()

        def _effective_total(self) -> float:
            return self.total if self.total > 0 else max(self._expected_total_bytes, 0.0)

        def _compute_percent(self) -> int:
            total = self._effective_total()
            return int(max(0.0, min((self.n / total) * 100.0, 100.0))) if total > 0 else 0

        def _emit_progress_locked(self) -> None:
            percent = self._compute_percent()
            if percent != self._last_percent:
                self._last_percent = percent
                callback(percent)

        def _emit_if_bytes_bar(self) -> None:
            """Check cancellation and emit progress if this is a download bytes bar."""
            _check_download_cancelled(cancel_check)
            if not self._is_download_bytes_bar:
                return
            with _ProgressTqdm._lock:
                self._emit_progress_locked()

        def __iter__(self) -> Iterator[Any]:
            for item in self._iterable or ():
                _check_download_cancelled(cancel_check)
                yield item

        def __len__(self) -> int:
            if isinstance(self._iterable, Sized):
                return len(self._iterable)
            return 0

        def update(self, n: float = 1.0) -> None:
            _check_download_cancelled(cancel_check)
            if not self._is_download_bytes_bar:
                return
            with _ProgressTqdm._lock:
                self.n += float(n or 0)
                self._emit_progress_locked()

        def close(self) -> None:
            # No resources to release; required by tqdm interface contract.
            pass

        def __enter__(self) -> _ProgressTqdm:
            return self

        def __exit__(self, *args: object) -> None:
            del args
            self.close()

        def set_description(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def set_postfix(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def set_postfix_str(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def refresh(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self._emit_if_bytes_bar()

        def clear(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def reset(self, total: float | None = None) -> None:
            _check_download_cancelled(cancel_check)
            self.n = 0.0
            if total is not None:
                self.total = float(total)
            self._emit_if_bytes_bar()

        def display(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        @classmethod
        def get_lock(cls) -> threading.Lock:
            return cls._lock

        @classmethod
        def set_lock(cls, lock: threading.Lock) -> None:
            cls._lock = lock

        def moveto(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def unpause(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

    return _ProgressTqdm


def _resolve_download_size(
    model_name: str,
    repo_id: str,
) -> int | None:
    """Resolve total expected bytes for a model download, caching the result."""
    expected = _resolve_repo_total_bytes(repo_id)
    if expected is not None:
        with _MODEL_SIZE_CACHE_LOCK:
            _MODEL_SIZE_CACHE[_size_cache_key(model_name, RUNTIME_FASTER_WHISPER)] = expected
    if expected is None:
        expected = MODEL_ESTIMATED_SIZE_BYTES.get(model_name)
    return expected


def _prepare_faster_download_kwargs(
    model_name: str,
    repo_id: str,
    progress_callback: Callable[[int], None] | None,
    cancel_check: Callable[[], bool] | None,
) -> tuple[dict[str, Any], int | None]:
    """Build snapshot_download kwargs and resolve expected size."""
    kwargs: dict[str, Any] = {"repo_id": repo_id}
    expected_total_bytes: int | None = None
    if progress_callback is not None:
        if cancel_check is not None and cancel_check():
            raise DownloadCancelledError("Download cancelled before start")
        expected_total_bytes = _resolve_download_size(model_name, repo_id)
        kwargs["tqdm_class"] = _make_progress_tqdm(
            progress_callback,
            expected_total_bytes=expected_total_bytes,
            cancel_check=cancel_check,
        )
    return kwargs, expected_total_bytes


def _retry_download_in_subprocess(
    model_name: str,
    repo_id: str,
    exc: Exception,
    progress_callback: Callable[[int], None] | None,
    expected_total_bytes: int | None,
    cancel_check: Callable[[], bool] | None,
) -> Path:
    """Handle fds_to_keep errors by retrying the download in a subprocess."""
    logger.warning("Retrying model download in clean subprocess due to FD error")
    if cancel_check is not None and cancel_check():
        prune_invalid_model_cache(model_name)
        raise DownloadCancelledError("Download cancelled before retry") from exc
    try:
        return _download_model_in_subprocess(
            repo_id,
            progress_callback=progress_callback,
            expected_total_bytes=expected_total_bytes,
            cancel_check=cancel_check,
        )
    except Exception:
        prune_invalid_model_cache(model_name)
        raise


def _download_faster_model(
    model_name: str,
    progress_callback: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """
    Download and install the faster-whisper variant of a supported model into the local Hugging Face cache.

    Attempts to download the model snapshot for model_name from its configured Hugging Face repo into the local cache. If progress_callback is provided, reports byte progress and attempts to resolve the total size (falling back to an estimated size). If cancel_check signals cancellation at any point, raises DownloadCancelledError and prunes partially downloaded cache entries. On certain file-descriptor-related errors, retries the download in a clean subprocess. On other failures the function prunes invalid cache data and re-raises the underlying exception.

    Parameters:
        model_name (str): One of the supported MODEL_NAMES to download.
        progress_callback (Callable[[int], None] | None): Optional callback invoked with the number of bytes downloaded so far.
        cancel_check (Callable[[], bool] | None): Optional callable checked before and during transfer; if it returns True the download is cancelled.

    Returns:
        Path: Path to the installed model snapshot directory.

    Raises:
        ValueError: If model_name is not a known model.
        DownloadCancelledError: If cancel_check indicates cancellation before or during download.
        Exception: Propagates other errors raised during download after pruning invalid cache.
    """
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")

    repo_id = _model_repo_id(model_name)
    prune_invalid_model_cache(model_name)

    # HF Xet can trigger subprocess FD issues in some TUI/runtime contexts.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    logger.info("Downloading model %s", repo_id)

    kwargs, expected_total_bytes = _prepare_faster_download_kwargs(
        model_name, repo_id, progress_callback, cancel_check,
    )

    try:
        if cancel_check is not None:
            if cancel_check():
                raise DownloadCancelledError("Download cancelled before transfer")
            return _download_model_in_subprocess(
                repo_id,
                progress_callback=progress_callback,
                expected_total_bytes=expected_total_bytes,
                cancel_check=cancel_check,
            )
        return Path(snapshot_download(**kwargs))
    except DownloadCancelledError:
        prune_invalid_model_cache(model_name)
        raise
    except Exception as exc:
        if "fds_to_keep" not in str(exc):
            prune_invalid_model_cache(model_name)
            raise
        return _retry_download_in_subprocess(
            model_name, repo_id, exc, progress_callback, expected_total_bytes, cancel_check,
        )


def _download_whisper_cpp_model(
    model_name: str,
    progress_callback: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """
    Download and return the local path to the whisper.cpp model file, downloading it from the remote repository if not already cached.

    Parameters:
        model_name: Supported model identifier (e.g., "tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo").
        progress_callback: Optional callable invoked with an integer progress percentage (0–100) to report download progress.
        cancel_check: Optional callable that should return True to signal cancellation; if it returns True before or during download, the operation is aborted.

    Returns:
        Path: Path to the existing or newly downloaded whisper.cpp model file.

    Raises:
        ValueError: If model_name is not a recognized model.
        DownloadCancelledError: If cancel_check signals cancellation before or after transfer.
    """
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")
    filename = whisper_cpp_model_filename(model_name)
    existing = get_installed_whisper_cpp_model_path(model_name)
    if existing is not None:
        if progress_callback is not None:
            progress_callback(100)
        return existing

    if cancel_check is not None and cancel_check():
        raise DownloadCancelledError("Download cancelled before start")

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    logger.info("Downloading whisper.cpp model %s (%s)", model_name, filename)
    if progress_callback is not None:
        progress_callback(0)
    downloaded = Path(
        hf_hub_download(repo_id=WHISPER_CPP_REPO_ID, filename=filename)
    )
    if cancel_check is not None and cancel_check():
        raise DownloadCancelledError("Download cancelled after transfer")
    with _MODEL_SIZE_CACHE_LOCK:
        try:
            _MODEL_SIZE_CACHE[_size_cache_key(model_name, RUNTIME_WHISPER_CPP)] = downloaded.stat().st_size
        except OSError:
            pass
    if progress_callback is not None:
        progress_callback(100)
    return downloaded


def download_model(
    model_name: str,
    runtime: str | None = "faster-whisper",
    progress_callback: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """
    Download and install a model variant for the requested runtime.

    Parameters:
        model_name (str): Supported model name to download.
        runtime (str | None): Runtime whose model variant should be downloaded.
        progress_callback (Callable[[int], None] | None): Optional callback receiving integer progress 0-100.
        cancel_check (Callable[[], bool] | None): Optional cancellation signal function.

    Returns:
        Path: Filesystem path to the downloaded model artifact.
    """
    operations = _model_operations_for_runtime(runtime)
    return operations.download(
        model_name,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def ensure_model_available(
    model_name: str, runtime: str | None = "faster-whisper"
) -> Path:
    """
    Ensure the specified model variant for the given runtime is installed and return its local snapshot path.

    Parameters:
        model_name (str): Supported model name (for example "tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo").
        runtime (str | None): Target runtime variant; normalized to either "faster-whisper" or "whisper.cpp". Defaults to "faster-whisper".

    Returns:
        Path: Filesystem path to the installed model snapshot.
    """
    installed_path = get_installed_model_path(model_name, runtime=runtime)
    if installed_path is not None:
        return installed_path
    normalized = normalize_model_runtime(runtime)
    if normalized == "faster-whisper":
        # Keep legacy invocation shape for callsites/tests that patch download_model.
        return download_model(model_name)
    return download_model(model_name, runtime=normalized)


def _terminate_subprocess(process: subprocess.Popen[str]) -> None:
    """Terminate a subprocess, escalating to kill if it does not exit promptly."""
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            return
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass


def _make_subprocess_progress_emitter(
    cache_path: Path,
    progress_callback: Callable[[int], None] | None,
    expected_total_bytes: int | None,
    scan_interval: float = 5.0,
) -> Callable[[], int]:
    """Create a closure that computes and emits cache-size-based progress. Returns current last_percent."""
    last_percent = -1
    last_size = 0
    last_scan_time = 0.0

    def emit_progress() -> int:
        nonlocal last_percent, last_size, last_scan_time
        if progress_callback is None:
            return last_percent

        current_time = time.monotonic()
        total = int(expected_total_bytes or 0)
        if total <= 0:
            percent = 0
        else:
            if current_time - last_scan_time >= scan_interval:
                last_size = _cache_path_size_bytes(cache_path)
                last_scan_time = current_time
            percent = int(max(0.0, min((last_size / float(total)) * 100.0, 99.0)))

        if percent != last_percent:
            last_percent = percent
            progress_callback(percent)
        return last_percent

    return emit_progress


def _download_model_in_subprocess(
    repo_id: str,
    progress_callback: Callable[[int], None] | None = None,
    expected_total_bytes: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """
    Download a Hugging Face model snapshot for the given repository in a separate subprocess while reporting progress and honoring cancellation.

    When provided, progress_callback receives integer percentage updates (0–100). If expected_total_bytes is given and greater than zero, percentages are estimated from the on-disk cache size and capped at 99% until the subprocess completes; a final 100% update is emitted on success. The cancel_check callable, when it returns True during the operation, causes the download to be terminated and the partial cache to be pruned.

    Parameters:
        repo_id (str): Hugging Face repository identifier to download.
        progress_callback (Callable[[int], None] | None): Optional callback invoked with integer percent progress (0–100).
        expected_total_bytes (int | None): Optional expected total size in bytes used to estimate progress percentages.
        cancel_check (Callable[[], bool] | None): Optional callable checked periodically; if it returns True the download is cancelled.

    Returns:
        Path: Filesystem path to the downloaded model snapshot.

    Raises:
        DownloadCancelledError: If cancellation is requested via cancel_check during the download.
        RuntimeError: If the subprocess fails or does not return a valid path.
    """
    env = os.environ.copy()
    env["HF_HUB_DISABLE_XET"] = "1"
    env["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    env["HF_HUB_DISABLE_TQDM"] = "1"
    script = (
        "from huggingface_hub import snapshot_download; "
        f"print(snapshot_download(repo_id={repo_id!r}))"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )

    cache_path = _cache_path_for_repo_id(repo_id)
    emit_progress = _make_subprocess_progress_emitter(
        cache_path, progress_callback, expected_total_bytes,
    )

    while process.poll() is None:
        if cancel_check is not None and cancel_check():
            _terminate_subprocess(process)
            _prune_cache_path(cache_path)
            raise DownloadCancelledError("Download cancelled during shutdown")

        emit_progress()
        time.sleep(0.2)

    stdout, _ = process.communicate()
    if process.returncode:
        _prune_cache_path(cache_path)
        details = (stdout or "").strip()
        raise RuntimeError(
            f"Model download subprocess failed for {repo_id}" + (f": {details}" if details else "")
        )

    last_percent = emit_progress()

    output = stdout.strip().splitlines()
    if not output:
        _prune_cache_path(cache_path)
        raise RuntimeError("No model path returned by download subprocess")
    if progress_callback is not None and last_percent < 100:
        progress_callback(100)
    return Path(output[-1])


def _remove_faster_model(model_name: str) -> None:
    """
    Remove all cached installations of the faster-whisper variant for the given model.

    Parameters:
        model_name (str): Supported model identifier (e.g., "tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo").
    """
    for cache_path in _model_cache_paths(model_name):
        if cache_path.exists():
            shutil.rmtree(cache_path)


def _remove_whisper_cpp_model(model_name: str) -> None:
    """
    Remove installed whisper.cpp model files and clean up empty snapshot directories.

    Deletes the whisper.cpp model file corresponding to `model_name` from all
    snapshot directories inside the local Hugging Face cache. If a snapshot
    directory becomes empty after removing the file, the directory is removed.
    Individual failures to delete files or directories are ignored (a warning is
    emitted) and do not raise.
    Parameters:
    	model_name (str): Name of the model (e.g., "tiny", "base", "small") whose
    	whisper.cpp binary should be removed.
    """
    filename = whisper_cpp_model_filename(model_name)
    snapshots = _whisper_cpp_snapshots_dir()
    if not snapshots.exists():
        return
    for snapshot in snapshots.iterdir():
        if not snapshot.is_dir():
            continue
        candidate = snapshot / filename
        if candidate.exists():
            try:
                candidate.unlink()
            except Exception:
                logger.warning("Failed to remove whisper.cpp model file: %s", candidate)
        try:
            if not any(snapshot.iterdir()):
                snapshot.rmdir()
        except Exception:
            continue


def remove_model(model_name: str, runtime: str | None = "faster-whisper") -> None:
    """
    Remove locally cached files for the specified model variant and clear its size cache entry.

    Parameters:
    	model_name: Supported model name whose cached files should be removed.
    	runtime: Runtime variant to remove (e.g., "faster-whisper" or "whisper.cpp"); defaults to the faster-whisper variant.
    """
    if model_name not in MODEL_NAMES:
        return
    normalized = normalize_model_runtime(runtime)
    operations = _model_operations_for_runtime(normalized)
    operations.remove(model_name)
    with _MODEL_SIZE_CACHE_LOCK:
        _MODEL_SIZE_CACHE.pop(_size_cache_key(model_name, normalized), None)


def set_selected_model(model_name: str, path: Path | None = None) -> None:
    """
    Selects a model in the persisted configuration and clears any configured model path.

    Parameters:
        model_name: Model identifier to select; must be one of the supported model names.
        path: Optional path to the configuration file or directory; if omitted, the default config location is used.

    Raises:
        ValueError: If `model_name` is not a supported model.
    """
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")
    config = config_module.load_config(path)
    config.model.name = model_name
    config.model.path = None
    config_module.save_config(config, path)


def set_default_model(model_name: str, path: Path | None = None) -> None:
    """
    Set the selected model in the application configuration (backwards-compatible alias).

    Parameters:
        model_name (str): Name of the model to select.
        path (Path | None): Optional path to a specific installed model snapshot to store; if None the stored path is cleared.
    """
    set_selected_model(model_name, path)
