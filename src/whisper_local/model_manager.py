from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Set before importing huggingface_hub so it applies reliably.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from huggingface_hub import snapshot_download

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


def download_model(model_name: str) -> Path:
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")
    repo_id = f"{MODEL_REPO_PREFIX}{model_name}"
    # HF Xet can trigger subprocess FD issues in some TUI/runtime contexts.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    logger.info("Downloading model %s", repo_id)
    try:
        return Path(snapshot_download(repo_id=repo_id))
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


def set_default_model(model_name: str, path: Path | None = None) -> None:
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")
    config = config_module.load_config(path)
    config.model.name = model_name
    config.model.path = None
    config_module.save_config(config, path)
