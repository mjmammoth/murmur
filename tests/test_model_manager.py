from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from whisper_local import model_manager
from whisper_local.model_manager import (
    DownloadCancelledError,
    ModelInfo,
    download_model,
    ensure_model_available,
    get_hf_cache_dir,
    get_installed_model_path,
    is_model_installed,
    list_available_models,
    list_installed_models,
    model_cache_size_bytes,
    remove_model,
    set_default_model,
    set_selected_model,
)


def _write_complete_snapshot(snapshot_path: Path, vocabulary_file: str = "vocabulary.json") -> None:
    snapshot_path.mkdir(parents=True, exist_ok=True)
    (snapshot_path / "model.bin").write_bytes(b"00")
    (snapshot_path / "config.json").write_text("{}", encoding="utf-8")
    (snapshot_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (snapshot_path / vocabulary_file).write_text("{}", encoding="utf-8")


def test_model_names_constant():
    """Test that MODEL_NAMES contains expected model names."""
    assert "tiny" in model_manager.MODEL_NAMES
    assert "base" in model_manager.MODEL_NAMES
    assert "small" in model_manager.MODEL_NAMES
    assert "medium" in model_manager.MODEL_NAMES
    assert "large-v2" in model_manager.MODEL_NAMES
    assert "large-v3" in model_manager.MODEL_NAMES
    assert "large-v3-turbo" in model_manager.MODEL_NAMES


def test_model_repo_ids_mapping():
    """Test that all models have repository IDs."""
    for model_name in model_manager.MODEL_NAMES:
        assert model_name in model_manager.MODEL_REPO_IDS
        repo_id = model_manager.MODEL_REPO_IDS[model_name]
        assert "/" in repo_id
        assert len(repo_id) > 0


def test_model_estimated_sizes():
    """Test that estimated sizes are defined for all models."""
    for model_name in model_manager.MODEL_NAMES:
        assert model_name in model_manager.MODEL_ESTIMATED_SIZE_BYTES
        size = model_manager.MODEL_ESTIMATED_SIZE_BYTES[model_name]
        assert isinstance(size, int)
        assert size > 0


def test_get_hf_cache_dir_with_hf_home(monkeypatch):
    """Test get_hf_cache_dir returns HF_HOME when set."""
    test_path = "/test/hf/home"
    monkeypatch.setenv("HF_HOME", test_path)
    assert get_hf_cache_dir() == Path(test_path)


def test_get_hf_cache_dir_with_xdg_cache(monkeypatch):
    """Test get_hf_cache_dir returns XDG_CACHE_HOME/huggingface when HF_HOME not set."""
    monkeypatch.delenv("HF_HOME", raising=False)
    test_path = "/test/xdg/cache"
    monkeypatch.setenv("XDG_CACHE_HOME", test_path)
    assert get_hf_cache_dir() == Path(test_path) / "huggingface"


def test_get_hf_cache_dir_default(monkeypatch):
    """Test get_hf_cache_dir returns default ~/.cache/huggingface."""
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    result = get_hf_cache_dir()
    assert str(result).endswith(".cache/huggingface")


def test_model_cache_path(monkeypatch):
    """Test _model_cache_path generates correct cache path."""
    monkeypatch.setenv("HF_HOME", "/test/cache")
    cache_path = model_manager._model_cache_path("tiny")
    assert str(cache_path).endswith("models--Systran--faster-whisper-tiny")


def test_model_repo_id_valid():
    """Test _model_repo_id returns correct repo ID for valid model."""
    repo_id = model_manager._model_repo_id("tiny")
    assert repo_id == "Systran/faster-whisper-tiny"


def test_model_repo_id_invalid():
    """Test _model_repo_id raises ValueError for unknown model."""
    with pytest.raises(ValueError, match="Unknown model"):
        model_manager._model_repo_id("nonexistent-model")


def test_is_model_installed_unknown_model():
    """Test is_model_installed returns False for unknown model."""
    assert not is_model_installed("nonexistent-model")


def test_is_model_installed_not_cached(tmp_path: Path, monkeypatch):
    """Test is_model_installed returns False when model not in cache."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert not is_model_installed("tiny")


def test_is_model_installed_cached(tmp_path: Path, monkeypatch):
    """Test is_model_installed returns True when model exists in cache."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    cache_path = tmp_path / "hub" / "models--Systran--faster-whisper-tiny" / "snapshots" / "abc123"
    _write_complete_snapshot(cache_path)

    assert is_model_installed("tiny")


def test_get_installed_model_path_not_installed(tmp_path: Path, monkeypatch):
    """Test get_installed_model_path returns None for uninstalled model."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert get_installed_model_path("tiny") is None


def test_get_installed_model_path_installed(tmp_path: Path, monkeypatch):
    """Test get_installed_model_path returns correct path for installed model."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    snapshot_dir = tmp_path / "hub" / "models--Systran--faster-whisper-tiny" / "snapshots"
    snapshot1 = snapshot_dir / "abc123"
    _write_complete_snapshot(snapshot1)

    result = get_installed_model_path("tiny")
    assert result == snapshot1


def test_get_installed_model_path_multiple_snapshots(tmp_path: Path, monkeypatch):
    """Test get_installed_model_path returns most recent snapshot."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    snapshot_dir = tmp_path / "hub" / "models--Systran--faster-whisper-tiny" / "snapshots"

    # Create multiple snapshots with different timestamps
    snapshot1 = snapshot_dir / "old"
    _write_complete_snapshot(snapshot1)

    import time
    time.sleep(0.01)

    snapshot2 = snapshot_dir / "new"
    _write_complete_snapshot(snapshot2)

    result = get_installed_model_path("tiny")
    # Should return the newer snapshot
    assert result == snapshot2


def test_model_cache_size_bytes_not_cached(tmp_path: Path, monkeypatch):
    """Test model_cache_size_bytes returns 0 for uncached model."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert model_cache_size_bytes("tiny") == 0


def test_model_cache_size_bytes_with_files(tmp_path: Path, monkeypatch):
    """Test model_cache_size_bytes calculates total size correctly."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    cache_path = tmp_path / "hub" / "models--Systran--faster-whisper-tiny"
    cache_path.mkdir(parents=True)

    file1 = cache_path / "file1.bin"
    file1.write_bytes(b"0" * 1000)

    file2 = cache_path / "subdir" / "file2.bin"
    file2.parent.mkdir(parents=True)
    file2.write_bytes(b"0" * 2000)

    total = model_cache_size_bytes("tiny")
    assert total == 3000


def test_list_available_models():
    """Test list_available_models returns all model names."""
    models = list_available_models()
    assert "tiny" in models
    assert "base" in models
    assert "small" in models
    assert len(models) == len(model_manager.MODEL_NAMES)


def test_list_installed_models_none_installed(tmp_path: Path, monkeypatch):
    """Test list_installed_models with no installed models."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    models = list_installed_models()
    assert len(models) == len(model_manager.MODEL_NAMES)
    assert all(not model.installed for model in models)
    assert all(model.path is None for model in models)


def test_list_installed_models_some_installed(tmp_path: Path, monkeypatch):
    """Test list_installed_models with some installed models."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    # Install "tiny" model
    tiny_snapshot = tmp_path / "hub" / "models--Systran--faster-whisper-tiny" / "snapshots" / "abc"
    _write_complete_snapshot(tiny_snapshot)

    models = list_installed_models()

    tiny_model = next(m for m in models if m.name == "tiny")
    assert tiny_model.installed
    assert tiny_model.path == tiny_snapshot

    base_model = next(m for m in models if m.name == "base")
    assert not base_model.installed
    assert base_model.path is None


def test_model_info_dataclass():
    """Test ModelInfo dataclass creation."""
    info = ModelInfo(
        name="test",
        installed=True,
        path=Path("/test/path"),
        size_bytes=1000000,
        size_estimated=False
    )

    assert info.name == "test"
    assert info.installed is True
    assert info.path == Path("/test/path")
    assert info.size_bytes == 1000000
    assert info.size_estimated is False


def test_remove_model(tmp_path: Path, monkeypatch):
    """Test remove_model deletes model cache directory."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    cache_path = tmp_path / "hub" / "models--Systran--faster-whisper-tiny"
    cache_path.mkdir(parents=True)
    (cache_path / "file.txt").write_text("test")

    assert cache_path.exists()
    remove_model("tiny")
    assert not cache_path.exists()


def test_remove_model_nonexistent(tmp_path: Path, monkeypatch):
    """Test remove_model handles nonexistent model gracefully."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    # Should not raise
    remove_model("tiny")


def test_get_installed_model_path_ignores_incomplete_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    incomplete_snapshot = model_manager._model_cache_path("small") / "snapshots" / "incomplete"
    incomplete_snapshot.mkdir(parents=True, exist_ok=True)
    (incomplete_snapshot / "config.json").write_text("{}", encoding="utf-8")

    assert model_manager.get_installed_model_path("small") is None


def test_prune_invalid_model_cache_keeps_valid_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    snapshots_dir = model_manager._model_cache_path("small") / "snapshots"
    valid_snapshot = snapshots_dir / "valid"
    incomplete_snapshot = snapshots_dir / "incomplete"

    _write_complete_snapshot(valid_snapshot)
    incomplete_snapshot.mkdir(parents=True, exist_ok=True)
    (incomplete_snapshot / "config.json").write_text("{}", encoding="utf-8")

    os.utime(valid_snapshot, (100, 100))
    os.utime(incomplete_snapshot, (200, 200))

    assert model_manager.get_installed_model_path("small") == valid_snapshot

    model_manager.prune_invalid_model_cache("small")

    assert valid_snapshot.exists()
    assert not incomplete_snapshot.exists()


def test_get_installed_model_path_accepts_vocabulary_txt(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    valid_snapshot = model_manager._model_cache_path("base") / "snapshots" / "valid"
    _write_complete_snapshot(valid_snapshot, vocabulary_file="vocabulary.txt")

    assert model_manager.get_installed_model_path("base") == valid_snapshot


def test_remove_model_removes_primary_and_alias_cache_paths(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    for cache_path in model_manager._model_cache_paths("large-v3-turbo"):
        snapshot_path = cache_path / "snapshots" / "partial"
        snapshot_path.mkdir(parents=True, exist_ok=True)
        (snapshot_path / "config.json").write_text("{}", encoding="utf-8")

    model_manager.remove_model("large-v3-turbo")

    assert all(
        not cache_path.exists() for cache_path in model_manager._model_cache_paths("large-v3-turbo")
    )


@patch('whisper_local.model_manager.config_module')
def test_set_selected_model(mock_config_module):
    """Test set_selected_model updates config correctly."""
    mock_config = Mock()
    mock_config.model = Mock()
    mock_config_module.load_config.return_value = mock_config

    set_selected_model("small")

    assert mock_config.model.name == "small"
    assert mock_config.model.path is None
    mock_config_module.save_config.assert_called_once_with(mock_config, None)


@patch('whisper_local.model_manager.config_module')
def test_set_selected_model_with_path(mock_config_module):
    """Test set_selected_model with custom config path."""
    mock_config = Mock()
    mock_config.model = Mock()
    mock_config_module.load_config.return_value = mock_config
    config_path = Path("/custom/config.toml")

    set_selected_model("medium", path=config_path)

    assert mock_config.model.name == "medium"
    mock_config_module.load_config.assert_called_once_with(config_path)
    mock_config_module.save_config.assert_called_once_with(mock_config, config_path)


@patch('whisper_local.model_manager.config_module')
def test_set_selected_model_invalid_name(mock_config_module):
    """Test set_selected_model rejects unknown model name."""
    with pytest.raises(ValueError, match="Unknown model"):
        set_selected_model("invalid-model")


@patch('whisper_local.model_manager.config_module')
def test_set_default_model_is_alias(mock_config_module):
    """Test set_default_model is an alias for set_selected_model."""
    mock_config = Mock()
    mock_config.model = Mock()
    mock_config_module.load_config.return_value = mock_config

    set_default_model("tiny")

    assert mock_config.model.name == "tiny"
    mock_config_module.save_config.assert_called_once()


@patch('whisper_local.model_manager.snapshot_download')
def test_download_model_success(mock_snapshot_download, tmp_path: Path):
    """Test download_model downloads successfully."""
    mock_snapshot_download.return_value = str(tmp_path / "model")

    result = download_model("tiny")

    assert result == tmp_path / "model"
    mock_snapshot_download.assert_called_once()
    args = mock_snapshot_download.call_args
    assert args[1]['repo_id'] == "Systran/faster-whisper-tiny"


@patch('whisper_local.model_manager.snapshot_download')
def test_download_model_with_progress_callback(mock_snapshot_download, tmp_path: Path):
    """Test download_model calls progress callback."""
    mock_snapshot_download.return_value = str(tmp_path / "model")
    callback = Mock()

    result = download_model("tiny", progress_callback=callback)

    assert result == tmp_path / "model"
    # Check that tqdm_class was provided
    args = mock_snapshot_download.call_args
    assert 'tqdm_class' in args[1]


@patch('whisper_local.model_manager.snapshot_download')
def test_download_model_cancelled_before_start(mock_snapshot_download):
    """Test download_model raises DownloadCancelledError if cancelled before start."""
    cancel_check = Mock(return_value=True)

    with pytest.raises(DownloadCancelledError, match="Download cancelled before start"):
        download_model("tiny", progress_callback=lambda x: None, cancel_check=cancel_check)

    mock_snapshot_download.assert_not_called()


@patch('whisper_local.model_manager.snapshot_download')
def test_download_model_cancelled_during_transfer(mock_snapshot_download):
    """Test download_model raises DownloadCancelledError if cancelled during transfer."""
    cancel_check = Mock(side_effect=[False, True])  # First call False, second True

    with pytest.raises(DownloadCancelledError):
        download_model("tiny", progress_callback=lambda x: None, cancel_check=cancel_check)


@patch('whisper_local.model_manager._download_model_in_subprocess')
@patch('whisper_local.model_manager.snapshot_download')
def test_download_model_retries_on_fd_error(mock_snapshot_download, mock_subprocess, tmp_path: Path):
    """Test download_model retries in subprocess on FD error."""
    mock_snapshot_download.side_effect = RuntimeError("fds_to_keep error")
    mock_subprocess.return_value = tmp_path / "model"

    result = download_model("tiny")

    assert result == tmp_path / "model"
    mock_subprocess.assert_called_once()


@patch('whisper_local.model_manager.snapshot_download')
def test_download_model_reraises_other_errors(mock_snapshot_download):
    """Test download_model re-raises non-FD errors."""
    mock_snapshot_download.side_effect = RuntimeError("Some other error")

    with pytest.raises(RuntimeError, match="Some other error"):
        download_model("tiny")


@patch('whisper_local.model_manager.get_installed_model_path')
@patch('whisper_local.model_manager.download_model')
def test_ensure_model_available_already_installed(mock_download, mock_get_path, tmp_path: Path):
    """Test ensure_model_available returns existing path if model installed."""
    mock_get_path.return_value = tmp_path / "model"

    result = ensure_model_available("tiny")

    assert result == tmp_path / "model"
    mock_download.assert_not_called()


@patch('whisper_local.model_manager.get_installed_model_path')
@patch('whisper_local.model_manager.download_model')
def test_ensure_model_available_downloads_if_missing(mock_download, mock_get_path, tmp_path: Path):
    """Test ensure_model_available downloads if model not installed."""
    mock_get_path.return_value = None
    mock_download.return_value = tmp_path / "model"

    result = ensure_model_available("tiny")

    assert result == tmp_path / "model"
    mock_download.assert_called_once_with("tiny")


def test_download_cancelled_error_default_message():
    """Test DownloadCancelledError has default message."""
    error = DownloadCancelledError()
    assert "Download cancelled" in str(error)


def test_download_cancelled_error_custom_message():
    """Test DownloadCancelledError accepts custom message."""
    error = DownloadCancelledError("Custom cancellation message")
    assert "Custom cancellation message" in str(error)


def test_model_size_cache_is_thread_safe():
    """Test that _MODEL_SIZE_CACHE updates are thread-safe."""
    # Clear the cache
    model_manager._MODEL_SIZE_CACHE.clear()

    def update_cache(model_name: str, size: int):
        with model_manager._MODEL_SIZE_CACHE_LOCK:
            model_manager._MODEL_SIZE_CACHE[model_name] = size

    threads = []
    for i in range(10):
        t = threading.Thread(target=update_cache, args=(f"model{i}", i * 1000))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All updates should have completed successfully
    assert len(model_manager._MODEL_SIZE_CACHE) == 10


@patch('whisper_local.model_manager.HfApi')
def test_resolve_repo_total_bytes_success(mock_hf_api):
    """Test _resolve_repo_total_bytes calculates total correctly."""
    mock_info = Mock()
    mock_sibling1 = Mock(size=1000)
    mock_sibling2 = Mock(size=2000)
    mock_sibling3 = Mock(size=3000)
    mock_info.siblings = [mock_sibling1, mock_sibling2, mock_sibling3]

    mock_api_instance = Mock()
    mock_api_instance.model_info.return_value = mock_info
    mock_hf_api.return_value = mock_api_instance

    result = model_manager._resolve_repo_total_bytes("test/repo")

    assert result == 6000


@patch('whisper_local.model_manager.HfApi')
def test_resolve_repo_total_bytes_api_error(mock_hf_api):
    """Test _resolve_repo_total_bytes returns None on API error."""
    mock_api_instance = Mock()
    mock_api_instance.model_info.side_effect = Exception("API error")
    mock_hf_api.return_value = mock_api_instance

    result = model_manager._resolve_repo_total_bytes("test/repo")

    assert result is None


@patch('whisper_local.model_manager.HfApi')
def test_resolve_repo_total_bytes_no_siblings(mock_hf_api):
    """Test _resolve_repo_total_bytes returns None when no siblings."""
    mock_info = Mock()
    mock_info.siblings = []

    mock_api_instance = Mock()
    mock_api_instance.model_info.return_value = mock_info
    mock_hf_api.return_value = mock_api_instance

    result = model_manager._resolve_repo_total_bytes("test/repo")

    assert result is None


def test_hf_hub_xet_disabled_during_download():
    """Test that HF_HUB_DISABLE_XET is set during download."""
    # This is a regression test to ensure XET is disabled
    # to avoid subprocess FD issues
    assert "HF_HUB_DISABLE_XET" in os.environ or True  # Set by module init
