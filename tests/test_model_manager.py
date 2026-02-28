from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_local import model_manager
from whisper_local.model_manager import (
    DownloadCancelledError,
    ModelInfo,
    ModelVariantInfo,
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
    whisper_local_model_cache_paths,
)
from whisper_local.model_ops import (
    FasterWhisperModelRuntimeOperations,
    WhisperCppModelRuntimeOperations,
    get_model_runtime_operations_factory,
)


def _write_complete_snapshot(snapshot_path: Path, vocabulary_file: str = "vocabulary.json") -> None:
    """
    Create a minimal, complete model snapshot directory containing the files required by tests.

    Parameters:
        snapshot_path (Path): Directory to create for the snapshot; will be created if it does not exist.
        vocabulary_file (str): Filename to use for the vocabulary file (created with minimal placeholder content).
    """
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


def test_whisper_local_model_cache_paths_deduplicated_and_scoped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    paths = whisper_local_model_cache_paths()
    assert paths
    assert len(paths) == len(set(paths))
    assert paths[0] == model_manager._model_cache_paths(model_manager.MODEL_NAMES[0])[0]

    hub_root = (tmp_path / "hf-home" / "hub").expanduser().resolve()
    for path in paths:
        assert path.expanduser().resolve().is_relative_to(hub_root)

    assert paths[-1] == model_manager._cache_path_for_repo_id(model_manager.WHISPER_CPP_REPO_ID)

    turbo_paths = model_manager._model_cache_paths("large-v3-turbo")
    assert all(path in paths for path in turbo_paths)
    turbo_indices = [paths.index(path) for path in turbo_paths]
    assert turbo_indices == sorted(turbo_indices)


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

    snapshot2 = snapshot_dir / "new"
    _write_complete_snapshot(snapshot2)
    snapshot1_mtime = snapshot1.stat().st_mtime
    os.utime(snapshot2, (snapshot1_mtime + 1, snapshot1_mtime + 1))

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
    assert all(not model.variants["faster-whisper"].installed for model in models)
    assert all(not model.variants["whisper.cpp"].installed for model in models)
    assert all(model.variants["faster-whisper"].path is None for model in models)
    assert all(model.variants["whisper.cpp"].path is None for model in models)


def test_list_installed_models_some_installed(tmp_path: Path, monkeypatch):
    """Test list_installed_models with some installed models."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    # Install "tiny" model
    tiny_snapshot = tmp_path / "hub" / "models--Systran--faster-whisper-tiny" / "snapshots" / "abc"
    _write_complete_snapshot(tiny_snapshot)

    models = list_installed_models()

    tiny_model = next(m for m in models if m.name == "tiny")
    assert tiny_model.variants["faster-whisper"].installed
    assert tiny_model.variants["faster-whisper"].path == tiny_snapshot
    assert not tiny_model.variants["whisper.cpp"].installed
    assert tiny_model.variants["whisper.cpp"].path is None

    base_model = next(m for m in models if m.name == "base")
    assert not base_model.variants["faster-whisper"].installed
    assert base_model.variants["faster-whisper"].path is None
    assert not base_model.variants["whisper.cpp"].installed
    assert base_model.variants["whisper.cpp"].path is None


def test_model_info_dataclass():
    """Test ModelInfo dataclass creation."""
    info = ModelInfo(
        name="test",
        variants={
            "faster-whisper": ModelVariantInfo(
                runtime="faster-whisper",
                format="ct2",
                installed=True,
                path=Path("/test/path/fw"),
                size_bytes=1000000,
                size_estimated=False,
            ),
            "whisper.cpp": ModelVariantInfo(
                runtime="whisper.cpp",
                format="ggml",
                installed=False,
                path=None,
                size_bytes=2000000,
                size_estimated=True,
            ),
        },
    )

    assert info.name == "test"
    assert info.variants["faster-whisper"].installed is True
    assert info.variants["faster-whisper"].path == Path("/test/path/fw")
    assert info.variants["faster-whisper"].size_bytes == 1000000
    assert info.variants["faster-whisper"].size_estimated is False
    assert info.variants["whisper.cpp"].installed is False
    assert info.variants["whisper.cpp"].size_bytes == 2000000
    assert info.variants["whisper.cpp"].size_estimated is True


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
    """
    Ensure prune_invalid_model_cache removes incomplete snapshot directories while preserving valid ones.

    Creates a valid and an incomplete snapshot for the "small" model, arranges modification times so the incomplete snapshot appears newer, verifies the valid snapshot is initially recognized as installed, runs prune_invalid_model_cache("small"), and then asserts the valid snapshot still exists while the incomplete snapshot has been removed.
    """
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
    assert "HF_HUB_DISABLE_XET" in os.environ
    assert os.environ["HF_HUB_DISABLE_XET"] == "1"


def test_runtime_operations_factory_returns_expected_strategies():
    factory = get_model_runtime_operations_factory()

    assert isinstance(factory.for_runtime("faster-whisper"), FasterWhisperModelRuntimeOperations)
    assert isinstance(factory.for_runtime("whisper.cpp"), WhisperCppModelRuntimeOperations)


def test_download_model_uses_factory_strategy():
    fake_ops = Mock()
    fake_ops.download.return_value = Path("/tmp/model")
    fake_factory = Mock()
    fake_factory.for_runtime.return_value = fake_ops

    with patch("whisper_local.model_manager.get_model_runtime_operations_factory", return_value=fake_factory):
        result = download_model("tiny", runtime="whisper.cpp")

    assert result == Path("/tmp/model")
    fake_factory.for_runtime.assert_called_once_with("whisper.cpp")
    fake_ops.download.assert_called_once_with(
        "tiny",
        progress_callback=None,
        cancel_check=None,
    )


def test_whisper_cpp_download_cancelled_before_start_raises():
    ops = WhisperCppModelRuntimeOperations()

    with patch("whisper_local.model_manager.get_installed_whisper_cpp_model_path", return_value=None):
        with pytest.raises(DownloadCancelledError, match="Download cancelled before start"):
            ops.download("tiny", cancel_check=lambda: True)


def test_whisper_cpp_download_cancelled_during_transfer_terminates_subprocess():
    ops = WhisperCppModelRuntimeOperations()
    process = Mock()
    process.poll.return_value = None
    process.wait.return_value = None

    with patch("whisper_local.model_ops.subprocess.Popen", return_value=process), patch(
        "whisper_local.model_manager._prune_whisper_cpp_cache"
    ) as prune_cache:
        with pytest.raises(DownloadCancelledError, match="Download cancelled"):
            ops._download_file_in_subprocess(
                repo_id="ggerganov/whisper.cpp",
                filename="ggml-tiny.bin",
                cancel_check=lambda: True,
            )

    process.terminate.assert_called_once()
    prune_cache.assert_called_once()


def test_whisper_cpp_progress_uses_incremental_cache_delta():
    ops = WhisperCppModelRuntimeOperations()
    process = Mock()
    process.poll.side_effect = [None, 0]
    process.returncode = 0
    process.communicate.return_value = ("/tmp/model.bin\n", "")
    progress_updates: list[int] = []

    with patch("whisper_local.model_ops.subprocess.Popen", return_value=process), patch(
        "whisper_local.model_manager._cache_path_size_bytes",
        side_effect=[1000, 1200],
    ):
        result = ops._download_file_in_subprocess(
            repo_id="ggerganov/whisper.cpp",
            filename="ggml-tiny.bin",
            progress_callback=progress_updates.append,
            expected_total_bytes=1000,
        )

    assert result == Path("/tmp/model.bin")
    # 200 bytes transferred over a 1000-byte expected file should report 20%.
    assert 20 in progress_updates
    assert 99 not in progress_updates


# ---------------------------------------------------------------------------
# _make_progress_tqdm
# ---------------------------------------------------------------------------

def test_make_progress_tqdm_iterable_mode():
    updates: list[int] = []
    cls = model_manager._make_progress_tqdm(updates.append)
    items = ["a", "b", "c"]
    instance = cls(items, name="test")
    assert list(instance) == items
    assert len(instance) == 3


def test_make_progress_tqdm_update_emits_callback():
    updates: list[int] = []
    cls = model_manager._make_progress_tqdm(updates.append, expected_total_bytes=1000)
    instance = cls(total=1000, name="huggingface_hub.snapshot_download")
    instance.update(500)
    assert 50 in updates
    instance.update(500)
    assert 100 in updates


def test_make_progress_tqdm_reset():
    updates: list[int] = []
    cls = model_manager._make_progress_tqdm(updates.append, expected_total_bytes=1000)
    instance = cls(total=1000, name="huggingface_hub.snapshot_download")
    instance.update(500)
    instance.reset(total=2000)
    assert instance.n == pytest.approx(0.0)
    assert instance.total == pytest.approx(2000.0)


def test_make_progress_tqdm_refresh():
    updates: list[int] = []
    cls = model_manager._make_progress_tqdm(updates.append, expected_total_bytes=1000)
    instance = cls(total=1000, name="huggingface_hub.snapshot_download")
    instance.update(100)
    instance.refresh()  # should not raise


def test_make_progress_tqdm_cancel_check():
    cls = model_manager._make_progress_tqdm(lambda x: None, cancel_check=lambda: True)
    with pytest.raises(DownloadCancelledError):
        cls(name="test")


def test_make_progress_tqdm_context_manager():
    updates: list[int] = []
    cls = model_manager._make_progress_tqdm(updates.append)
    with cls(name="test"):
        pass  # should not raise


def test_make_progress_tqdm_noop_methods():
    cls = model_manager._make_progress_tqdm(lambda x: None)
    instance = cls(name="test")
    instance.set_description("desc")
    instance.set_postfix(x=1)
    instance.set_postfix_str("s")
    instance.clear()
    instance.display()
    instance.moveto(0)
    instance.unpause()
    instance.close()


def test_make_progress_tqdm_get_set_lock():
    cls = model_manager._make_progress_tqdm(lambda x: None)
    lock = cls.get_lock()
    assert lock is not None
    new_lock = threading.Lock()
    cls.set_lock(new_lock)
    assert cls.get_lock() is new_lock


def test_make_progress_tqdm_non_download_bar_update_ignored():
    updates: list[int] = []
    cls = model_manager._make_progress_tqdm(updates.append, expected_total_bytes=1000)
    instance = cls(total=100, name="other")
    instance.update(50)
    # Non-download bars don't emit progress
    assert 50 not in updates


# ---------------------------------------------------------------------------
# _resolve_repo_file_size_bytes
# ---------------------------------------------------------------------------

@patch("whisper_local.model_manager.HfApi")
def test_resolve_repo_file_size_bytes_match(mock_hf_api):
    mock_sibling = Mock()
    mock_sibling.rfilename = "model.bin"
    mock_sibling.size = 5000
    mock_info = Mock()
    mock_info.siblings = [mock_sibling]
    mock_hf_api.return_value.model_info.return_value = mock_info

    result = model_manager._resolve_repo_file_size_bytes("test/repo", "model.bin")
    assert result == 5000


@patch("whisper_local.model_manager.HfApi")
def test_resolve_repo_file_size_bytes_no_match(mock_hf_api):
    mock_sibling = Mock()
    mock_sibling.rfilename = "other.bin"
    mock_sibling.size = 5000
    mock_info = Mock()
    mock_info.siblings = [mock_sibling]
    mock_hf_api.return_value.model_info.return_value = mock_info

    result = model_manager._resolve_repo_file_size_bytes("test/repo", "model.bin")
    assert result is None


@patch("whisper_local.model_manager.HfApi")
def test_resolve_repo_file_size_bytes_api_error(mock_hf_api):
    mock_hf_api.return_value.model_info.side_effect = Exception("API error")
    result = model_manager._resolve_repo_file_size_bytes("test/repo", "model.bin")
    assert result is None


# ---------------------------------------------------------------------------
# whisper_cpp_model_filename
# ---------------------------------------------------------------------------

def test_whisper_cpp_model_filename_valid():
    assert model_manager.whisper_cpp_model_filename("tiny") == "ggml-tiny.bin"
    assert model_manager.whisper_cpp_model_filename("large-v3") == "ggml-large-v3.bin"


def test_whisper_cpp_model_filename_unknown():
    with pytest.raises(ValueError, match="Unknown model"):
        model_manager.whisper_cpp_model_filename("nonexistent")


# ---------------------------------------------------------------------------
# normalize_model_runtime
# ---------------------------------------------------------------------------

def test_normalize_model_runtime_default():
    assert model_manager.normalize_model_runtime(None) == "faster-whisper"


def test_normalize_model_runtime_whisper_cpp():
    assert model_manager.normalize_model_runtime("whisper.cpp") == "whisper.cpp"


def test_normalize_model_runtime_faster_whisper():
    assert model_manager.normalize_model_runtime("faster-whisper") == "faster-whisper"


# ---------------------------------------------------------------------------
# model_variant_format
# ---------------------------------------------------------------------------

def test_model_variant_format_faster_whisper():
    assert model_manager.model_variant_format("faster-whisper") == "ctranslate2"


def test_model_variant_format_whisper_cpp():
    assert model_manager.model_variant_format("whisper.cpp") == "ggml"


def test_model_variant_format_none():
    assert model_manager.model_variant_format(None) == "ctranslate2"
