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
from typing import Callable

# Set before importing huggingface_hub so it applies reliably.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from huggingface_hub import HfApi, snapshot_download

from whisper_local import config as config_module


logger = logging.getLogger(__name__)

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
_MODEL_SIZE_CACHE: dict[str, int] = {}
_MODEL_SIZE_CACHE_LOCK = threading.Lock()


class DownloadCancelledError(RuntimeError):
    """Raised when a model download is cancelled by shutdown."""

    def __init__(self, message: str = "Download cancelled") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class ModelInfo:
    name: str
    installed: bool
    path: Path | None = None
    size_bytes: int | None = None
    size_estimated: bool = False


def get_hf_cache_dir() -> Path:
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home)
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "huggingface"
    return Path("~/.cache/huggingface").expanduser()


def _model_cache_path(model_name: str) -> Path:
    """
    Return the primary Hugging Face cache directory path for the given model.
    
    Returns:
        Path: The primary cache path for `model_name`.
    """
    return _model_cache_paths(model_name)[0]


def _cache_path_for_repo_id(repo_id: str) -> Path:
    """
    Return the local Hugging Face cache path corresponding to a model repository id.
    
    Parameters:
        repo_id (str): Hugging Face repository identifier (e.g., "owner/model").
    
    Returns:
        Path: Filesystem path to the model cache directory inside the Hugging Face hub cache (e.g., ~/.cache/huggingface/hub/models--owner--model).
    """
    cache_name = f"models--{repo_id.replace('/', '--')}"
    return get_hf_cache_dir() / "hub" / cache_name


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
    Return all cache directory paths that may contain snapshots for the specified model.
    
    Parameters:
        model_name (str): Supported model name.
    
    Returns:
        tuple[Path, ...]: Tuple of filesystem paths for each repository ID associated with the model, ordered with the primary repository first followed by any aliases.
    """
    return tuple(_cache_path_for_repo_id(repo_id) for repo_id in _model_repo_ids(model_name))


def _model_repo_id(model_name: str) -> str:
    """
    Resolve the primary repository identifier for a given model name.
    
    Returns:
        repo_id (str): The primary repository ID associated with the model.
    
    Raises:
        ValueError: If the provided model_name is not recognized.
    """
    repo_id = MODEL_REPO_IDS.get(model_name)
    if not repo_id:
        raise ValueError(f"Unknown model: {model_name}")
    return repo_id


def is_model_installed(model_name: str) -> bool:
    """
    Check whether a supported model has a complete installed snapshot in the local cache.
    
    Returns:
        `true` if the model is installed and a complete snapshot path exists, `false` otherwise.
    """
    if model_name not in MODEL_NAMES:
        return False
    return get_installed_model_path(model_name) is not None


def get_installed_model_path(model_name: str) -> Path | None:
    """
    Locate the most recently installed complete snapshot path for a given model.
    
    Scans the model's cache locations and returns the most recently modified snapshot directory that contains all required model files.
    
    Parameters:
        model_name (str): The canonical name of the model to search for.
    
    Returns:
        Path | None: Path to the most recent complete snapshot directory for the model, or `None` if the model name is unknown or no complete snapshot is found.
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


def _cache_path_size_bytes(cache_path: Path) -> int:
    """
    Compute the total size in bytes of all files under a cache directory.
    
    Parameters:
        cache_path (Path): Path to the cache directory to measure.
    
    Returns:
        int: Sum of sizes (in bytes) of all files under `cache_path`. Returns 0 if `cache_path` does not exist.
    """
    if not cache_path.exists():
        return 0
    total = 0
    for path in cache_path.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _iter_snapshot_paths(cache_path: Path) -> list[Path]:
    """
    Return a list of snapshot directory paths found under the repository cache's "snapshots" subdirectory.
    
    Parameters:
    	cache_path (Path): Path to the repository cache directory that may contain a "snapshots" folder.
    
    Returns:
    	snapshots (list[Path]): List of Paths for each immediate subdirectory inside `<cache_path>/snapshots`; empty list if no snapshots directory exists.
    """
    snapshots_path = cache_path / "snapshots"
    if not snapshots_path.exists():
        return []
    return [path for path in snapshots_path.iterdir() if path.is_dir()]


def _snapshot_is_complete(snapshot_path: Path) -> bool:
    """
    Check whether a model snapshot directory contains all required non-empty files and at least one non-empty file from each alternative group.
    
    Parameters:
        snapshot_path (Path): Path to the candidate snapshot directory to validate.
    
    Returns:
        True if every filename listed in MODEL_REQUIRED_FILES exists in the directory and has size greater than zero, and for each group in MODEL_REQUIRED_FILE_ALTERNATIVES at least one file exists and is non-empty; False otherwise.
    """
    def has_nonempty_file(filename: str) -> bool:
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


def _prune_cache_path(cache_path: Path) -> None:
    """
    Remove incomplete model snapshot data and orphaned partial blobs from a model cache path.
    
    Prunes any snapshot directories under `cache_path` that are not complete, removes `.incomplete` files under `cache_path/blobs`, and if the cache contains no remaining snapshot directories removes the entire `cache_path`. Failures to remove individual files or directories are logged but do not raise.
    """
    removed_any = False
    for snapshot_path in _iter_snapshot_paths(cache_path):
        if _snapshot_is_complete(snapshot_path):
            continue
        try:
            shutil.rmtree(snapshot_path)
            removed_any = True
        except Exception:
            logger.warning("Failed to remove incomplete model snapshot: %s", snapshot_path)

    blobs_path = cache_path / "blobs"
    if blobs_path.exists():
        for partial_path in blobs_path.glob("*.incomplete"):
            try:
                partial_path.unlink()
                removed_any = True
            except Exception:
                logger.warning("Failed to remove partial model blob: %s", partial_path)

    if not removed_any:
        return

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


def prune_invalid_model_caches() -> None:
    """
    Prune incomplete or invalid cache snapshots for all configured models.
    
    Removes incomplete snapshots, partial blobs, and empty cache directories for every model known to the application.
    """
    for model_name in MODEL_NAMES:
        prune_invalid_model_cache(model_name)


def model_cache_size_bytes(model_name: str) -> int:
    """
    Compute the total size of all cache directories for the specified model.
    
    Parameters:
        model_name (str): The model's canonical name.
    
    Returns:
        int: Total size in bytes of all cached snapshots and related files for the model.
    """
    total = 0
    for cache_path in _model_cache_paths(model_name):
        total += _cache_path_size_bytes(cache_path)
    return total


def list_available_models() -> list[str]:
    """
    List supported model names available for download or selection.
    
    Returns:
        list[str]: A list of supported model name strings.
    """
    return list(MODEL_NAMES)


def list_installed_models() -> list[ModelInfo]:
    models = []
    for name in MODEL_NAMES:
        installed_path = get_installed_model_path(name)
        with _MODEL_SIZE_CACHE_LOCK:
            exact_size = _MODEL_SIZE_CACHE.get(name)
        estimated_size = MODEL_ESTIMATED_SIZE_BYTES.get(name)
        size_bytes = exact_size if exact_size is not None else estimated_size
        models.append(
            ModelInfo(
                name=name,
                installed=installed_path is not None,
                path=installed_path,
                size_bytes=size_bytes,
                size_estimated=exact_size is None and size_bytes is not None,
            )
        )
    return models


def _resolve_repo_total_bytes(repo_id: str) -> int | None:
    """
    Compute the total size in bytes of all artifact files for a Hugging Face repository.
    
    Queries the repository's files metadata and sums the sizes of files that report a positive integer size; returns `None` when metadata cannot be retrieved or yields no positive sizes.
    
    Returns:
        int: Total size in bytes of all files, `None` if unavailable.
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


def _make_progress_tqdm(
    callback: Callable[[int], None],
    expected_total_bytes: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
):
    """Create a tqdm-compatible class that reports download progress via callback.

    ``snapshot_download`` uses the class in two ways:
      1. As an **iterable wrapper** for the file list: ``for f in tqdm_class(files):``
      2. As a **byte-level progress bar** for each file download (total= bytes).
    The class must support both modes.
    """

    class _ProgressTqdm:
        _lock = threading.Lock()

        @staticmethod
        def _raise_if_cancelled() -> None:
            if cancel_check is not None and cancel_check():
                raise DownloadCancelledError("Download cancelled during shutdown")

        def __init__(self, iterable=None, *args, **kwargs):
            _ProgressTqdm._raise_if_cancelled()
            # Iterable mode (file list wrapper)
            self._iterable = iterable
            self.total = float(kwargs.get("total", 0) or 0)
            self.n = float(kwargs.get("initial", 0) or 0)
            self.disable = kwargs.get("disable", False)
            self._expected_total_bytes = float(expected_total_bytes or 0)
            name = str(kwargs.get("name", ""))
            unit = str(kwargs.get("unit", "")).upper()
            self._is_download_bytes_bar = (
                name == "huggingface_hub.snapshot_download" or unit == "B"
            )
            self._last_percent = -1
            if self._is_download_bytes_bar:
                self._emit_progress_locked()

        def _effective_total(self) -> float:
            if self.total > 0:
                return self.total
            if self._expected_total_bytes > 0:
                return self._expected_total_bytes
            return 0.0

        def _emit_progress_locked(self) -> None:
            total = self._effective_total()
            if total <= 0:
                percent = 0
            else:
                percent = int(max(0.0, min((self.n / total) * 100.0, 100.0)))
            if percent == self._last_percent:
                return
            self._last_percent = percent
            callback(percent)

        def __iter__(self):
            if self._iterable is not None:
                yield from self._iterable
            return

        def __len__(self):
            if self._iterable is not None:
                try:
                    return len(self._iterable)
                except TypeError:
                    return 0
            return 0

        def update(self, n=1):
            _ProgressTqdm._raise_if_cancelled()
            if not self._is_download_bytes_bar:
                return

            with _ProgressTqdm._lock:
                self.n += float(n or 0)
                self._emit_progress_locked()

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def set_description(self, *args, **kwargs):
            pass

        def set_postfix(self, *args, **kwargs):
            pass

        def set_postfix_str(self, *args, **kwargs):
            pass

        def refresh(self, *args, **kwargs):
            _ProgressTqdm._raise_if_cancelled()
            if not self._is_download_bytes_bar:
                return
            with _ProgressTqdm._lock:
                self._emit_progress_locked()

        def clear(self, *args, **kwargs):
            pass

        def reset(self, total=None):
            _ProgressTqdm._raise_if_cancelled()
            with _ProgressTqdm._lock:
                self.n = 0.0
                if total is not None:
                    self.total = float(total)
                if self._is_download_bytes_bar:
                    self._emit_progress_locked()

        def display(self, *args, **kwargs):
            pass

        @classmethod
        def get_lock(cls):
            return cls._lock

        @classmethod
        def set_lock(cls, lock):
            cls._lock = lock

        def moveto(self, *args, **kwargs):
            pass

        def unpause(self, *args, **kwargs):
            pass

    # Reset class-level counters for each download
    return _ProgressTqdm


def download_model(
    model_name: str,
    progress_callback: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """
    Download the given model and return the local snapshot path.
    
    Parameters:
        model_name (str): Name of the model to download; must be one of the supported model names.
        progress_callback (Callable[[int], None] | None): Optional callback receiving download progress as an integer percentage (0–100).
        cancel_check (Callable[[], bool] | None): Optional callable that returns True to request cancellation; checked before start and during transfer.
    
    Returns:
        path (Path): Filesystem path to the downloaded model snapshot.
    
    Raises:
        ValueError: If `model_name` is not a known supported model.
        DownloadCancelledError: If cancellation is requested before or during download.
    """
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")

    repo_id = _model_repo_id(model_name)
    prune_invalid_model_cache(model_name)

    # HF Xet can trigger subprocess FD issues in some TUI/runtime contexts.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    logger.info("Downloading model %s", repo_id)

    kwargs: dict = {"repo_id": repo_id}
    expected_total_bytes: int | None = None
    if progress_callback is not None:
        if cancel_check is not None and cancel_check():
            raise DownloadCancelledError("Download cancelled before start")
        expected_total_bytes = _resolve_repo_total_bytes(repo_id)
        if expected_total_bytes is not None:
            with _MODEL_SIZE_CACHE_LOCK:
                _MODEL_SIZE_CACHE[model_name] = expected_total_bytes
        if expected_total_bytes is None:
            expected_total_bytes = MODEL_ESTIMATED_SIZE_BYTES.get(model_name)
        kwargs["tqdm_class"] = _make_progress_tqdm(
            progress_callback,
            expected_total_bytes=expected_total_bytes,
            cancel_check=cancel_check,
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


def ensure_model_available(model_name: str) -> Path:
    """
    Ensure the specified model is installed and return the local snapshot path.
    
    Parameters:
        model_name (str): Name of the model to ensure is available (one of the supported model names).
    
    Returns:
        Path: Filesystem path to the installed model snapshot.
    """
    installed_path = get_installed_model_path(model_name)
    if installed_path is not None:
        return installed_path
    return download_model(model_name)


def _download_model_in_subprocess(
    repo_id: str,
    progress_callback: Callable[[int], None] | None = None,
    expected_total_bytes: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """
    Downloads the specified Hugging Face repository snapshot in a separate subprocess while optionally reporting progress and honoring cancellation.
    
    Parameters:
        repo_id (str): Hugging Face repository identifier to download.
        progress_callback (Callable[[int], None] | None): Optional callback receiving integer percentage progress (0–100).
        expected_total_bytes (int | None): Optional expected total size in bytes used to compute progress percentages when available.
        cancel_check (Callable[[], bool] | None): Optional callable checked periodically; if it returns True the download is cancelled.
    
    Returns:
        Path: Filesystem path to the downloaded model snapshot.
    
    Raises:
        DownloadCancelledError: If cancellation is requested via `cancel_check` during the download.
        RuntimeError: If the subprocess fails or does not return a valid path.
    """
    env = os.environ.copy()
    env["HF_HUB_DISABLE_XET"] = "1"
    env["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    script = (
        "from huggingface_hub import snapshot_download; "
        f"print(snapshot_download(repo_id={repo_id!r}))"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    cache_path = _cache_path_for_repo_id(repo_id)
    last_percent = -1
    last_size = 0
    last_scan_time = 0.0
    SIZE_SCAN_INTERVAL = 5.0

    def emit_progress() -> None:
        """
        Update progress by computing the download percentage from the cache path size and invoking the progress callback when the reported percent changes.
        
        If `expected_total_bytes` is missing or zero, reports `0%`. When a total is known, the cache path size is refreshed at most once per `SIZE_SCAN_INTERVAL` and used to compute an integer percentage capped at `99%` until completion. The `progress_callback` is called with the new percent only if it differs from the last emitted value.
        """
        nonlocal last_percent, last_size, last_scan_time
        if progress_callback is None:
            return

        current_time = time.monotonic()
        total = int(expected_total_bytes or 0)
        if total <= 0:
            percent = 0
        else:
            if current_time - last_scan_time >= SIZE_SCAN_INTERVAL:
                last_size = _cache_path_size_bytes(cache_path)
                last_scan_time = current_time
            downloaded = last_size
            percent = int(max(0.0, min((downloaded / float(total)) * 100.0, 99.0)))

        if percent == last_percent:
            return

        last_percent = percent
        progress_callback(percent)

    while process.poll() is None:
        if cancel_check is not None and cancel_check():
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
            _prune_cache_path(cache_path)
            raise DownloadCancelledError("Download cancelled during shutdown")

        emit_progress()
        time.sleep(0.2)

    stdout, stderr = process.communicate()
    if process.returncode:
        _prune_cache_path(cache_path)
        details = (stderr or stdout).strip()
        raise RuntimeError(
            f"Model download subprocess failed for {repo_id}" + (f": {details}" if details else "")
        )

    emit_progress()

    output = stdout.strip().splitlines()
    if not output:
        _prune_cache_path(cache_path)
        raise RuntimeError("No model path returned by download subprocess")
    if progress_callback is not None and last_percent < 100:
        progress_callback(100)
    return Path(output[-1])


def remove_model(model_name: str) -> None:
    """
    Remove all cached installations for the given model.
    
    This deletes every cache directory associated with the model (including repo aliases)
    from the Hugging Face cache. If the model name is not recognized, the function does nothing.
    
    Parameters:
        model_name (str): Supported model name whose cached files should be removed.
    """
    if model_name not in MODEL_NAMES:
        return
    for cache_path in _model_cache_paths(model_name):
        if cache_path.exists():
            shutil.rmtree(cache_path)


def set_selected_model(model_name: str, path: Path | None = None) -> None:
    """
    Set the selected model name in the configuration and clear any stored model path.
    
    Parameters:
        model_name (str): Name of the model to select; must be one of the supported model names.
        path (Path | None): Optional path to the configuration file or directory. If None, the default config location is used.
    
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
    """Backward-compatible alias for pre-select command naming."""
    set_selected_model(model_name, path)