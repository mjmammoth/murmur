from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import whisper_local
from whisper_local.model_ops import (
    DefaultModelRuntimeOperationsFactory,
    FasterWhisperModelRuntimeOperations,
    WhisperCppModelRuntimeOperations,
    get_model_runtime_operations_factory,
)


def _patch_mm(mock_mm):
    """Patch model_manager on the whisper_local package so lazy imports resolve to mock_mm."""
    return patch.object(whisper_local, "model_manager", mock_mm)


def test_faster_whisper_runtime_operations_download():
    """Test FasterWhisperModelRuntimeOperations.download delegates to model_manager."""
    ops = FasterWhisperModelRuntimeOperations()
    assert ops.runtime == "faster-whisper"

    mock_mm = Mock()
    mock_mm._download_faster_model.return_value = Path("/path/to/model")

    with _patch_mm(mock_mm):
        result = ops.download("tiny")

        assert result == Path("/path/to/model")
        mock_mm._download_faster_model.assert_called_once_with(
            "tiny", progress_callback=None, cancel_check=None
        )


def test_faster_whisper_runtime_operations_download_with_callbacks():
    """Test FasterWhisperModelRuntimeOperations.download passes callbacks."""
    ops = FasterWhisperModelRuntimeOperations()
    progress_cb = Mock()
    cancel_cb = Mock()

    mock_mm = Mock()
    mock_mm._download_faster_model.return_value = Path("/path/to/model")

    with _patch_mm(mock_mm):
        ops.download("small", progress_callback=progress_cb, cancel_check=cancel_cb)

        mock_mm._download_faster_model.assert_called_once_with(
            "small", progress_callback=progress_cb, cancel_check=cancel_cb
        )


def test_faster_whisper_runtime_operations_remove():
    """Test FasterWhisperModelRuntimeOperations.remove delegates to model_manager."""
    ops = FasterWhisperModelRuntimeOperations()

    mock_mm = Mock()

    with _patch_mm(mock_mm):
        ops.remove("base")
        mock_mm._remove_faster_model.assert_called_once_with("base")


def test_faster_whisper_runtime_operations_installed_path():
    """Test FasterWhisperModelRuntimeOperations.installed_path delegates to model_manager."""
    ops = FasterWhisperModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm._get_installed_faster_model_path.return_value = Path("/models/base")

    with _patch_mm(mock_mm):
        result = ops.installed_path("base")

        assert result == Path("/models/base")
        mock_mm._get_installed_faster_model_path.assert_called_once_with("base")


def test_faster_whisper_runtime_operations_installed_path_not_found():
    """Test FasterWhisperModelRuntimeOperations.installed_path returns None when not found."""
    ops = FasterWhisperModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm._get_installed_faster_model_path.return_value = None

    with _patch_mm(mock_mm):
        result = ops.installed_path("nonexistent")

        assert result is None


def test_faster_whisper_runtime_operations_cache_size_bytes():
    """Test FasterWhisperModelRuntimeOperations.cache_size_bytes delegates to model_manager."""
    ops = FasterWhisperModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm._faster_model_cache_size_bytes.return_value = 1024000

    with _patch_mm(mock_mm):
        result = ops.cache_size_bytes("tiny")

        assert result == 1024000
        mock_mm._faster_model_cache_size_bytes.assert_called_once_with("tiny")


def test_faster_whisper_runtime_operations_estimated_size_bytes():
    """Test FasterWhisperModelRuntimeOperations.estimated_size_bytes returns model size."""
    ops = FasterWhisperModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm.MODEL_ESTIMATED_SIZE_BYTES = {"tiny": 75 * 1024 * 1024}

    with _patch_mm(mock_mm):
        result = ops.estimated_size_bytes("tiny")
        assert result == 75 * 1024 * 1024


def test_faster_whisper_runtime_operations_estimated_size_bytes_unknown():
    """Test FasterWhisperModelRuntimeOperations.estimated_size_bytes returns None for unknown."""
    ops = FasterWhisperModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm.MODEL_ESTIMATED_SIZE_BYTES = {}

    with _patch_mm(mock_mm):
        result = ops.estimated_size_bytes("unknown")
        assert result is None


def test_whisper_cpp_runtime_operations_download_existing_model():
    """Test WhisperCppModelRuntimeOperations.download returns existing model."""
    ops = WhisperCppModelRuntimeOperations()
    assert ops.runtime == "whisper.cpp"

    mock_mm = Mock()
    mock_mm.MODEL_NAMES = ["tiny", "base"]
    mock_mm.whisper_cpp_model_filename.return_value = "ggml-tiny.bin"
    mock_mm.get_installed_whisper_cpp_model_path.return_value = Path("/models/ggml-tiny.bin")

    progress_cb = Mock()

    with _patch_mm(mock_mm):
        result = ops.download("tiny", progress_callback=progress_cb)

        assert result == Path("/models/ggml-tiny.bin")
        progress_cb.assert_called_once_with(100)


def test_whisper_cpp_runtime_operations_download_unknown_model():
    """Test WhisperCppModelRuntimeOperations.download raises ValueError for unknown model."""
    ops = WhisperCppModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm.MODEL_NAMES = ["tiny", "base"]

    with _patch_mm(mock_mm):
        with pytest.raises(ValueError, match="Unknown model"):
            ops.download("nonexistent")


def test_whisper_cpp_runtime_operations_remove():
    """Test WhisperCppModelRuntimeOperations.remove delegates to model_manager."""
    ops = WhisperCppModelRuntimeOperations()

    mock_mm = Mock()

    with _patch_mm(mock_mm):
        ops.remove("tiny")
        mock_mm._remove_whisper_cpp_model.assert_called_once_with("tiny")


def test_whisper_cpp_runtime_operations_installed_path():
    """Test WhisperCppModelRuntimeOperations.installed_path delegates to model_manager."""
    ops = WhisperCppModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm.get_installed_whisper_cpp_model_path.return_value = Path("/models/ggml-base.bin")

    with _patch_mm(mock_mm):
        result = ops.installed_path("base")

        assert result == Path("/models/ggml-base.bin")
        mock_mm.get_installed_whisper_cpp_model_path.assert_called_once_with("base")


def test_whisper_cpp_runtime_operations_cache_size_bytes():
    """Test WhisperCppModelRuntimeOperations.cache_size_bytes delegates to model_manager."""
    ops = WhisperCppModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm._whisper_cpp_model_cache_size_bytes.return_value = 2048000

    with _patch_mm(mock_mm):
        result = ops.cache_size_bytes("base")

        assert result == 2048000
        mock_mm._whisper_cpp_model_cache_size_bytes.assert_called_once_with("base")


def test_whisper_cpp_runtime_operations_estimated_size_bytes():
    """Test WhisperCppModelRuntimeOperations.estimated_size_bytes returns model size."""
    ops = WhisperCppModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm.WHISPER_CPP_ESTIMATED_SIZE_BYTES = {"tiny": 75 * 1024 * 1024}

    with _patch_mm(mock_mm):
        result = ops.estimated_size_bytes("tiny")
        assert result == 75 * 1024 * 1024


def test_whisper_cpp_terminate_process_graceful():
    """Test _terminate_process handles graceful termination."""
    mock_process = Mock()
    mock_process.wait.return_value = None

    WhisperCppModelRuntimeOperations._terminate_process(mock_process)

    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_called_once()
    mock_process.kill.assert_not_called()


def test_whisper_cpp_terminate_process_forced():
    """Test _terminate_process forces kill on timeout."""
    mock_process = Mock()
    mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 2.0), None]

    WhisperCppModelRuntimeOperations._terminate_process(mock_process)

    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_called_once()
    assert mock_process.wait.call_count == 2


def test_default_factory_for_faster_whisper():
    """Test DefaultModelRuntimeOperationsFactory returns FasterWhisper ops."""
    factory = DefaultModelRuntimeOperationsFactory()

    ops = factory.for_runtime("faster-whisper")
    assert isinstance(ops, FasterWhisperModelRuntimeOperations)
    assert ops.runtime == "faster-whisper"


def test_default_factory_for_whisper_cpp():
    """Test DefaultModelRuntimeOperationsFactory returns WhisperCpp ops."""
    factory = DefaultModelRuntimeOperationsFactory()

    ops = factory.for_runtime("whisper.cpp")
    assert isinstance(ops, WhisperCppModelRuntimeOperations)
    assert ops.runtime == "whisper.cpp"


def test_default_factory_normalizes_runtime_name():
    """Test DefaultModelRuntimeOperationsFactory normalizes runtime names."""
    factory = DefaultModelRuntimeOperationsFactory()

    ops = factory.for_runtime("whisper-cpp")
    assert isinstance(ops, WhisperCppModelRuntimeOperations)

    ops = factory.for_runtime("whispercpp")
    assert isinstance(ops, WhisperCppModelRuntimeOperations)


def test_default_factory_default_runtime():
    """Test DefaultModelRuntimeOperationsFactory defaults to faster-whisper."""
    factory = DefaultModelRuntimeOperationsFactory()

    ops = factory.for_runtime(None)
    assert isinstance(ops, FasterWhisperModelRuntimeOperations)

    ops = factory.for_runtime("")
    assert isinstance(ops, FasterWhisperModelRuntimeOperations)


def test_default_factory_unknown_runtime():
    """Test DefaultModelRuntimeOperationsFactory falls back to faster-whisper for unknown."""
    factory = DefaultModelRuntimeOperationsFactory()

    with patch("whisper_local.config.logger"):
        ops = factory.for_runtime("unknown-runtime")
        assert isinstance(ops, FasterWhisperModelRuntimeOperations)


def test_default_factory_caches_operations():
    """Test DefaultModelRuntimeOperationsFactory reuses same operation instances."""
    factory = DefaultModelRuntimeOperationsFactory()

    ops1 = factory.for_runtime("faster-whisper")
    ops2 = factory.for_runtime("faster-whisper")

    assert ops1 is ops2


def test_get_model_runtime_operations_factory():
    """Test get_model_runtime_operations_factory returns the default factory."""
    factory = get_model_runtime_operations_factory()
    assert isinstance(factory, DefaultModelRuntimeOperationsFactory)


def test_faster_whisper_operations_has_correct_runtime_type():
    """Test FasterWhisperModelRuntimeOperations runtime type annotation."""
    ops = FasterWhisperModelRuntimeOperations()
    assert ops.runtime == "faster-whisper"


def test_whisper_cpp_operations_has_correct_runtime_type():
    """Test WhisperCppModelRuntimeOperations runtime type annotation."""
    ops = WhisperCppModelRuntimeOperations()
    assert ops.runtime == "whisper.cpp"


def test_whisper_cpp_download_file_subprocess_handles_cancel():
    """Test _download_file_in_subprocess cancels download when requested."""
    ops = WhisperCppModelRuntimeOperations()
    cancel_cb = Mock(side_effect=[False, True])

    mock_mm = Mock()
    mock_mm._cache_path_for_repo_id.return_value = Path("/cache")
    mock_mm._cache_path_size_bytes.return_value = 0
    mock_mm.DownloadCancelledError = Exception

    mock_process = Mock()
    mock_process.poll.side_effect = [None, None]

    with _patch_mm(mock_mm), \
         patch("subprocess.Popen", return_value=mock_process), \
         patch("time.sleep"):

        with pytest.raises(Exception):
            ops._download_file_in_subprocess(
                repo_id="test/repo",
                filename="model.bin",
                cancel_check=cancel_cb,
            )

        mock_process.terminate.assert_called()


def test_whisper_cpp_download_file_subprocess_handles_failure():
    """Test _download_file_in_subprocess raises on subprocess failure."""
    ops = WhisperCppModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm._cache_path_for_repo_id.return_value = Path("/cache")
    mock_mm._cache_path_size_bytes.return_value = 0

    mock_process = Mock()
    mock_process.poll.return_value = 1
    mock_process.returncode = 1
    mock_process.communicate.return_value = ("", "Connection failed")

    with _patch_mm(mock_mm), \
         patch("subprocess.Popen", return_value=mock_process), \
         patch("time.sleep"):

        with pytest.raises(RuntimeError, match="whisper.cpp model download subprocess failed"):
            ops._download_file_in_subprocess(
                repo_id="test/repo",
                filename="model.bin",
            )


def test_whisper_cpp_download_file_subprocess_no_output():
    """Test _download_file_in_subprocess raises when subprocess returns no output."""
    ops = WhisperCppModelRuntimeOperations()

    mock_mm = Mock()
    mock_mm._cache_path_for_repo_id.return_value = Path("/cache")
    mock_mm._cache_path_size_bytes.return_value = 0

    mock_process = Mock()
    mock_process.poll.return_value = 0
    mock_process.returncode = 0
    mock_process.communicate.return_value = ("", "")

    with _patch_mm(mock_mm), \
         patch("subprocess.Popen", return_value=mock_process), \
         patch("time.sleep"):

        with pytest.raises(RuntimeError, match="No model path returned"):
            ops._download_file_in_subprocess(
                repo_id="test/repo",
                filename="model.bin",
            )
