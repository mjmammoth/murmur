from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Set before importing huggingface_hub so it applies reliably.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from huggingface_hub import HfApi, snapshot_download

from whisper_local import config as config_module


logger = logging.getLogger(__name__)

MODEL_NAMES = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
MODEL_REPO_PREFIX = "Systran/faster-whisper-"


@dataclass(frozen=True)
class ModelInfo:
    name: str
    installed: bool
    path: Path | None = None


def get_hf_cache_dir() -> Path:
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home)
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "huggingface"
    return Path("~/.cache/huggingface").expanduser()


def _model_cache_path(model_name: str) -> Path:
    return get_hf_cache_dir() / "hub" / f"models--Systran--faster-whisper-{model_name}"


def is_model_installed(model_name: str) -> bool:
    if model_name not in MODEL_NAMES:
        return False
    return get_installed_model_path(model_name) is not None


def get_installed_model_path(model_name: str) -> Path | None:
    if model_name not in MODEL_NAMES:
        return None
    cache_path = _model_cache_path(model_name)
    snapshots_path = cache_path / "snapshots"
    if not snapshots_path.exists():
        return None
    candidates = [path for path in snapshots_path.iterdir() if path.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def model_cache_size_bytes(model_name: str) -> int:
    cache_path = _model_cache_path(model_name)
    if not cache_path.exists():
        return 0
    total = 0
    for path in cache_path.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def list_available_models() -> list[str]:
    return list(MODEL_NAMES)


def list_installed_models() -> list[ModelInfo]:
    models = []
    for name in MODEL_NAMES:
        installed_path = get_installed_model_path(name)
        models.append(ModelInfo(name=name, installed=installed_path is not None, path=installed_path))
    return models


def _resolve_repo_total_bytes(repo_id: str) -> int | None:
    """Return the total model artifact size in bytes, if available."""
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
):
    """Create a tqdm-compatible class that reports download progress via callback.

    ``snapshot_download`` uses the class in two ways:
      1. As an **iterable wrapper** for the file list: ``for f in tqdm_class(files):``
      2. As a **byte-level progress bar** for each file download (total= bytes).
    The class must support both modes.
    """

    class _ProgressTqdm:
        _total_bytes: int = 0
        _downloaded_bytes: int = 0
        _expected_total_bytes: int = expected_total_bytes or 0
        _last_percent: int = 0
        _lock = threading.Lock()

        def __init__(self, iterable=None, *args, **kwargs):
            # Iterable mode (file list wrapper)
            self._iterable = iterable
            # Byte-progress mode
            self.total = kwargs.get("total", 0) or 0
            self.n = 0
            self.disable = kwargs.get("disable", False)
            self._is_byte_bar = self._iterable is None and self.total > 0
            if self._is_byte_bar and _ProgressTqdm._expected_total_bytes <= 0:
                _ProgressTqdm._total_bytes += self.total

        def __iter__(self):
            if self._iterable is not None:
                yield from self._iterable
            return

        def __len__(self):
            if self._iterable is not None:
                return len(self._iterable)
            return 0

        def update(self, n=1):
            self.n += n
            if not self._is_byte_bar:
                return

            with _ProgressTqdm._lock:
                _ProgressTqdm._downloaded_bytes += n
                total_bytes = (
                    _ProgressTqdm._expected_total_bytes
                    if _ProgressTqdm._expected_total_bytes > 0
                    else _ProgressTqdm._total_bytes
                )
                if total_bytes <= 0:
                    return

                pct = int((_ProgressTqdm._downloaded_bytes / total_bytes) * 100)
                pct = max(0, min(pct, 100))
                if _ProgressTqdm._expected_total_bytes <= 0:
                    # Without server metadata, late-discovered file sizes can
                    # skew totals; keep headroom for final completion.
                    pct = min(pct, 95)
                pct = max(pct, _ProgressTqdm._last_percent)
                _ProgressTqdm._last_percent = pct

            callback(pct)

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
            pass

        def clear(self, *args, **kwargs):
            pass

        def reset(self, total=None):
            self.n = 0
            if total is not None:
                self.total = total

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
    _ProgressTqdm._total_bytes = 0
    _ProgressTqdm._downloaded_bytes = 0
    _ProgressTqdm._last_percent = 0
    return _ProgressTqdm


def download_model(
    model_name: str,
    progress_callback: Callable[[int], None] | None = None,
) -> Path:
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")
    repo_id = f"{MODEL_REPO_PREFIX}{model_name}"
    # HF Xet can trigger subprocess FD issues in some TUI/runtime contexts.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    logger.info("Downloading model %s", repo_id)

    kwargs: dict = {"repo_id": repo_id}
    if progress_callback is not None:
        expected_total_bytes = _resolve_repo_total_bytes(repo_id)
        kwargs["tqdm_class"] = _make_progress_tqdm(
            progress_callback,
            expected_total_bytes=expected_total_bytes,
        )

    try:
        return Path(snapshot_download(**kwargs))
    except Exception as exc:
        if "fds_to_keep" not in str(exc):
            raise
        logger.warning("Retrying model download in clean subprocess due to FD error")
        return _download_model_in_subprocess(repo_id)


def ensure_model_available(model_name: str) -> Path:
    installed_path = get_installed_model_path(model_name)
    if installed_path is not None:
        return installed_path
    return download_model(model_name)


def _download_model_in_subprocess(repo_id: str) -> Path:
    env = os.environ.copy()
    env["HF_HUB_DISABLE_XET"] = "1"
    env["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    script = (
        "from huggingface_hub import snapshot_download; "
        "print(snapshot_download(repo_id='" + repo_id + "'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    output = result.stdout.strip().splitlines()
    if not output:
        raise RuntimeError("No model path returned by download subprocess")
    return Path(output[-1])


def remove_model(model_name: str) -> None:
    cache_path = _model_cache_path(model_name)
    if cache_path.exists():
        shutil.rmtree(cache_path)


def set_selected_model(model_name: str, path: Path | None = None) -> None:
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")
    config = config_module.load_config(path)
    config.model.name = model_name
    config.model.path = None
    config_module.save_config(config, path)


def set_default_model(model_name: str, path: Path | None = None) -> None:
    """Backward-compatible alias for pre-select command naming."""
    set_selected_model(model_name, path)
