from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

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


def list_available_models() -> list[str]:
    return list(MODEL_NAMES)


def list_installed_models() -> list[ModelInfo]:
    models = []
    for name in MODEL_NAMES:
        cache_path = _model_cache_path(name)
        models.append(ModelInfo(name=name, installed=cache_path.exists(), path=cache_path))
    return models


def download_model(model_name: str) -> Path:
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")
    repo_id = f"{MODEL_REPO_PREFIX}{model_name}"
    logger.info("Downloading model %s", repo_id)
    return Path(snapshot_download(repo_id=repo_id))


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
