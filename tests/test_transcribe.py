from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

from whisper_local.transcribe import (
    FasterWhisperRuntime,
    TranscriptionResult,
    Transcriber,
    WhisperCppRuntime,
    detect_runtime_capabilities,
    ensure_whisper_cpp_installed,
    resample_audio,
)


def test_transcription_result_creation():
    """Test TranscriptionResult dataclass creation."""
    result = TranscriptionResult(text="hello world", language="en")
    assert result.text == "hello world"
    assert result.language == "en"


def test_transcription_result_no_language():
    """Test TranscriptionResult with no language."""
    result = TranscriptionResult(text="test", language=None)
    assert result.text == "test"
    assert result.language is None


def test_faster_whisper_runtime_init():
    """Test FasterWhisperRuntime initialization."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8", model_path="/custom/path")
    assert runtime.model_name == "tiny"
    assert runtime.device == "cpu"
    assert runtime.compute_type == "int8"
    assert runtime.model_path == "/custom/path"
    assert runtime.runtime_name == "faster-whisper"


def test_faster_whisper_runtime_resolve_model_source_custom_path():
    """Test FasterWhisperRuntime resolves custom model path."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8", model_path="/custom/model")
    source = runtime._resolve_model_source()
    assert source == "/custom/model"


def test_faster_whisper_runtime_resolve_model_source_from_cache():
    """Test FasterWhisperRuntime resolves model from cache."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8")

    with patch("whisper_local.transcribe.get_installed_model_path") as mock_path:
        mock_path.return_value = Path("/cache/tiny")
        source = runtime._resolve_model_source()

        assert source == str(Path("/cache/tiny"))
        mock_path.assert_called_once_with("tiny", runtime="faster-whisper")


def test_faster_whisper_runtime_resolve_model_source_not_installed():
    """Test FasterWhisperRuntime raises when model not installed."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8")

    with patch("whisper_local.transcribe.get_installed_model_path", return_value=None):
        with pytest.raises(RuntimeError, match="is not installed"):
            runtime._resolve_model_source()


def test_faster_whisper_runtime_load_missing_package():
    """Test FasterWhisperRuntime.load raises when faster-whisper not available."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8")

    with patch("whisper_local.transcribe.WhisperModel", None):
        with pytest.raises(RuntimeError, match="faster-whisper runtime unavailable"):
            runtime.load()


def test_faster_whisper_runtime_load_success():
    """Test FasterWhisperRuntime.load initializes model."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8")

    with patch("whisper_local.transcribe.WhisperModel") as mock_model_class, \
         patch("whisper_local.transcribe.get_installed_model_path", return_value=Path("/cache/tiny")), \
         patch("whisper_local.transcribe._resolve_faster_runtime", return_value=("cpu", "int8")):

        mock_model = Mock()
        mock_model_class.return_value = mock_model

        runtime.load()

        assert runtime._model == mock_model
        assert runtime._effective_device == "cpu"
        assert runtime._effective_compute_type == "int8"
        mock_model_class.assert_called_once_with("/cache/tiny", device="cpu", compute_type="int8")


def test_faster_whisper_runtime_transcribe_loads_model():
    """Test FasterWhisperRuntime.transcribe loads model if needed."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8")
    audio = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    mock_model = Mock()
    mock_segment = Mock()
    mock_segment.text = "hello"
    mock_info = Mock()
    mock_info.language = "en"
    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    with patch.object(runtime, "load") as mock_load:
        runtime._model = mock_model
        result = runtime.transcribe(audio, 16000)

        mock_load.assert_not_called()
        assert result.text == "hello"
        assert result.language == "en"


def test_faster_whisper_runtime_transcribe_handles_fd_error():
    """Test FasterWhisperRuntime.transcribe handles FD errors with reload."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8")
    audio = np.array([0.1, 0.2], dtype=np.float32)

    mock_model = Mock()
    mock_segment = Mock()
    mock_segment.text = "recovered"
    mock_info = Mock()
    mock_info.language = "en"

    # First call fails with FD error, second succeeds
    mock_model.transcribe.side_effect = [
        Exception("fds_to_keep error"),
        ([mock_segment], mock_info),
    ]

    runtime._model = mock_model

    with patch.object(runtime, "_reload_model_from_local") as mock_reload:
        result = runtime.transcribe(audio, 16000)

        mock_reload.assert_called_once()
        assert result.text == "recovered"


def test_faster_whisper_runtime_transcribe_falls_back_to_subprocess():
    """Test FasterWhisperRuntime.transcribe falls back to subprocess on repeated FD errors."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8")
    audio = np.array([0.1, 0.2], dtype=np.float32)

    mock_model = Mock()
    mock_model.transcribe.side_effect = Exception("fds_to_keep error")
    runtime._model = mock_model

    subprocess_result = TranscriptionResult(text="subprocess result", language="en")

    with patch.object(runtime, "_reload_model_from_local"), \
         patch.object(runtime, "_transcribe_in_subprocess", return_value=subprocess_result) as mock_subprocess:

        result = runtime.transcribe(audio, 16000)

        mock_subprocess.assert_called_once()
        assert result.text == "subprocess result"


def test_faster_whisper_runtime_transcribe_resamples_audio():
    """Test FasterWhisperRuntime.transcribe resamples audio to 16kHz."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8")
    audio = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)

    mock_model = Mock()
    mock_segment = Mock()
    mock_segment.text = "test"
    mock_info = Mock()
    mock_info.language = "en"
    mock_model.transcribe.return_value = ([mock_segment], mock_info)
    runtime._model = mock_model

    with patch("whisper_local.transcribe.resample_audio") as mock_resample:
        mock_resample.return_value = audio
        runtime.transcribe(audio, 48000)

        mock_resample.assert_called_once()
        args = mock_resample.call_args[0]
        assert args[1] == 48000
        assert args[2] == 16000


def test_faster_whisper_runtime_transcribe_subprocess():
    """Test FasterWhisperRuntime._transcribe_in_subprocess executes subprocess."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8")
    audio = np.array([0.1, 0.2], dtype=np.float32)

    with patch("whisper_local.transcribe.get_installed_model_path", return_value=Path("/cache/tiny")), \
         patch("whisper_local.transcribe._resolve_faster_runtime", return_value=("cpu", "int8")), \
         patch("subprocess.run") as mock_run:

        mock_result = Mock()
        mock_result.stdout = '{"text": "subprocess output", "language": "en"}\n'
        mock_run.return_value = mock_result

        result = runtime._transcribe_in_subprocess(audio, "en")

        assert result.text == "subprocess output"
        assert result.language == "en"
        mock_run.assert_called_once()


def test_faster_whisper_runtime_runtime_info():
    """Test FasterWhisperRuntime.runtime_info returns correct info."""
    runtime = FasterWhisperRuntime("tiny", "cpu", "int8", model_path="/custom")
    runtime._effective_device = "cpu"
    runtime._effective_compute_type = "int8"
    runtime._model_source = "/cache/tiny"

    info = runtime.runtime_info()

    assert info["runtime"] == "faster-whisper"
    assert info["effective_device"] == "cpu"
    assert info["effective_compute_type"] == "int8"
    assert info["model_source"] == "/cache/tiny"


def test_whisper_cpp_runtime_init():
    """Test WhisperCppRuntime initialization."""
    runtime = WhisperCppRuntime("tiny", "mps", "default", model_path="/custom/model.bin")
    assert runtime.model_name == "tiny"
    assert runtime.device == "mps"
    assert runtime.compute_type == "default"
    assert runtime.model_path == "/custom/model.bin"
    assert runtime.runtime_name == "whisper.cpp"


def test_whisper_cpp_runtime_load_binary_not_found():
    """Test WhisperCppRuntime.load raises when binary not found."""
    runtime = WhisperCppRuntime("tiny", "cpu", "default")

    with patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value=None):
        with pytest.raises(RuntimeError, match="whisper.cpp runtime unavailable"):
            runtime.load()


def test_whisper_cpp_runtime_load_custom_model_directory():
    """Test WhisperCppRuntime.load resolves model from custom directory."""
    runtime = WhisperCppRuntime("tiny", "cpu", "default", model_path="/models")

    with patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value="/usr/bin/whisper-cli"), \
         patch("whisper_local.transcribe._detect_whisper_cpp_gpu_control", return_value="no-gpu"):

        mock_path = Mock(spec=Path)
        mock_path.is_dir.return_value = True
        mock_path.glob.return_value = [Path("/models/ggml-tiny.bin")]

        with patch("pathlib.Path.expanduser", return_value=mock_path), \
             patch("pathlib.Path.exists", return_value=True):
            runtime.load()

            assert runtime._resolved_model_path == "/models/ggml-tiny.bin"
            assert runtime._binary_path == "/usr/bin/whisper-cli"


def test_whisper_cpp_runtime_load_custom_model_file():
    """Test WhisperCppRuntime.load resolves custom model file."""
    runtime = WhisperCppRuntime("tiny", "cpu", "default", model_path="/models/custom.bin")

    with patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value="/usr/bin/whisper-cli"), \
         patch("whisper_local.transcribe._detect_whisper_cpp_gpu_control", return_value="no-gpu"):

        mock_path = Mock(spec=Path)
        mock_path.is_dir.return_value = False
        mock_path.__str__ = Mock(return_value="/models/custom.bin")

        with patch("pathlib.Path.expanduser", return_value=mock_path), \
             patch("pathlib.Path.exists", return_value=True):
            runtime.load()

            assert runtime._resolved_model_path == "/models/custom.bin"


def test_whisper_cpp_runtime_load_model_not_found():
    """Test WhisperCppRuntime.load raises when model file doesn't exist."""
    runtime = WhisperCppRuntime("tiny", "cpu", "default", model_path="/nonexistent.bin")

    with patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value="/usr/bin/whisper-cli"), \
         patch("whisper_local.transcribe._detect_whisper_cpp_gpu_control", return_value="no-gpu"):

        mock_path = Mock(spec=Path)
        mock_path.is_dir.return_value = False
        mock_path.exists.return_value = False

        with patch("pathlib.Path.expanduser", return_value=mock_path):
            with pytest.raises(RuntimeError, match="does not exist"):
                runtime.load()


def test_whisper_cpp_runtime_load_from_cache():
    """Test WhisperCppRuntime.load loads model from cache."""
    runtime = WhisperCppRuntime("tiny", "cpu", "default")

    with patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value="/usr/bin/whisper-cli"), \
         patch("whisper_local.transcribe._detect_whisper_cpp_gpu_control", return_value="no-gpu"), \
         patch("whisper_local.transcribe.get_installed_model_path", return_value=Path("/cache/ggml-tiny.bin")):

        runtime.load()

        assert runtime._resolved_model_path == "/cache/ggml-tiny.bin"


def test_whisper_cpp_runtime_transcribe():
    """Test WhisperCppRuntime.transcribe executes whisper.cpp."""
    runtime = WhisperCppRuntime("tiny", "cpu", "default")
    runtime._binary_path = "/usr/bin/whisper-cli"
    runtime._resolved_model_path = "/models/ggml-tiny.bin"
    runtime._effective_device = "cpu"

    audio = np.array([0.1, 0.2], dtype=np.float32)

    with patch("subprocess.run") as mock_run, \
         patch("whisper_local.transcribe._write_wav_mono16"):

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        # Mock the output file
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value="transcribed text"):

            result = runtime.transcribe(audio, 16000, language="en")

            assert result.text == "transcribed text"
            assert result.language == "en"
            mock_run.assert_called_once()


def test_whisper_cpp_runtime_transcribe_with_gpu_device():
    """Test WhisperCppRuntime.transcribe uses GPU when device is not cpu."""
    runtime = WhisperCppRuntime("tiny", "mps", "default")
    runtime._binary_path = "/usr/bin/whisper-cli"
    runtime._resolved_model_path = "/models/ggml-tiny.bin"
    runtime._effective_device = "mps"

    audio = np.array([0.1, 0.2], dtype=np.float32)

    with patch("subprocess.run") as mock_run, \
         patch("whisper_local.transcribe._write_wav_mono16"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value="test"):

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        runtime.transcribe(audio, 16000)

        # Verify -ng (no-gpu) flag is NOT in command
        cmd = mock_run.call_args[0][0]
        assert "-ng" not in cmd


def test_whisper_cpp_runtime_transcribe_failure():
    """Test WhisperCppRuntime.transcribe raises on subprocess failure."""
    runtime = WhisperCppRuntime("tiny", "cpu", "default")
    runtime._binary_path = "/usr/bin/whisper-cli"
    runtime._resolved_model_path = "/models/ggml-tiny.bin"
    runtime._effective_device = "cpu"

    audio = np.array([0.1, 0.2], dtype=np.float32)

    with patch("subprocess.run") as mock_run, \
         patch("whisper_local.transcribe._write_wav_mono16"):

        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Model file not found"
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        with pytest.raises(RuntimeError, match="whisper.cpp transcription failed"):
            runtime.transcribe(audio, 16000)


def test_whisper_cpp_runtime_runtime_info():
    """Test WhisperCppRuntime.runtime_info returns correct info."""
    runtime = WhisperCppRuntime("tiny", "mps", "default")
    runtime._resolved_model_path = "/models/ggml-tiny.bin"
    runtime._effective_device = "mps"

    info = runtime.runtime_info()

    assert info["runtime"] == "whisper.cpp"
    assert info["effective_device"] == "mps"
    assert info["effective_compute_type"] == "default"
    assert info["model_source"] == "/models/ggml-tiny.bin"


def test_transcriber_init_faster_whisper():
    """Test Transcriber initialization with faster-whisper."""
    transcriber = Transcriber("tiny", "cpu", "int8", runtime="faster-whisper")

    assert transcriber.model_name == "tiny"
    assert transcriber.runtime == "faster-whisper"
    assert transcriber.device == "cpu"
    assert transcriber.compute_type == "int8"
    assert isinstance(transcriber._runtime_impl, FasterWhisperRuntime)


def test_transcriber_init_whisper_cpp():
    """Test Transcriber initialization with whisper.cpp."""
    transcriber = Transcriber("base", "mps", "default", runtime="whisper.cpp")

    assert transcriber.model_name == "base"
    assert transcriber.runtime == "whisper.cpp"
    assert isinstance(transcriber._runtime_impl, WhisperCppRuntime)


def test_transcriber_normalizes_runtime_name():
    """Test Transcriber normalizes runtime name."""
    transcriber = Transcriber("tiny", "cpu", "int8", runtime="whisper-cpp")
    assert transcriber.runtime == "whisper.cpp"


def test_transcriber_load():
    """Test Transcriber.load delegates to runtime implementation."""
    transcriber = Transcriber("tiny", "cpu", "int8")

    with patch.object(transcriber._runtime_impl, "load") as mock_load:
        transcriber.load()
        mock_load.assert_called_once()


def test_transcriber_transcribe():
    """Test Transcriber.transcribe delegates to runtime implementation."""
    transcriber = Transcriber("tiny", "cpu", "int8")
    audio = np.array([0.1, 0.2], dtype=np.float32)

    expected_result = TranscriptionResult(text="test", language="en")

    with patch.object(transcriber._runtime_impl, "transcribe", return_value=expected_result) as mock_transcribe:
        result = transcriber.transcribe(audio, 16000, language="en")

        assert result == expected_result
        mock_transcribe.assert_called_once_with(audio, 16000, "en")


def test_transcriber_runtime_info():
    """Test Transcriber.runtime_info includes model name."""
    transcriber = Transcriber("tiny", "cpu", "int8")

    with patch.object(transcriber._runtime_impl, "runtime_info", return_value={"runtime": "faster-whisper"}):
        info = transcriber.runtime_info()

        assert info["model_name"] == "tiny"
        assert info["runtime"] == "faster-whisper"


def test_detect_runtime_capabilities_faster_whisper_available():
    """Test detect_runtime_capabilities with faster-whisper available."""
    with patch("whisper_local.transcribe.WhisperModel", Mock()), \
         patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value="/usr/bin/whisper-cli"), \
         patch("whisper_local.transcribe._supported_compute_types", return_value=["int8", "float32"]), \
         patch("whisper_local.transcribe.ctranslate2") as mock_ct2:

        mock_ct2.get_cuda_device_count.return_value = 0

        caps = detect_runtime_capabilities("faster-whisper")

        assert caps["model"]["runtimes"]["faster-whisper"]["enabled"] is True
        assert caps["model"]["runtimes"]["whisper.cpp"]["enabled"] is True
        assert caps["model"]["devices"]["cpu"]["enabled"] is True
        assert caps["model"]["devices"]["cuda"]["enabled"] is False


def test_detect_runtime_capabilities_cuda_available():
    """Test detect_runtime_capabilities with CUDA available."""
    with patch("whisper_local.transcribe.WhisperModel", Mock()), \
         patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value=None), \
         patch("whisper_local.transcribe._supported_compute_types", return_value=["float16", "int8"]), \
         patch("whisper_local.transcribe.ctranslate2") as mock_ct2:

        mock_ct2.get_cuda_device_count.return_value = 1

        caps = detect_runtime_capabilities()

        assert caps["model"]["devices"]["cuda"]["enabled"] is True
        assert "CUDA" not in caps["model"]["devices"]["cuda"]["reason"] if caps["model"]["devices"]["cuda"]["reason"] else True


def test_detect_runtime_capabilities_whisper_cpp_macos():
    """Test detect_runtime_capabilities enables MPS on macOS."""
    with patch("whisper_local.transcribe.WhisperModel", None), \
         patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value="/usr/bin/whisper-cli"), \
         patch("whisper_local.transcribe._supported_compute_types", return_value=[]), \
         patch("whisper_local.transcribe.sys.platform", "darwin"):

        caps = detect_runtime_capabilities("whisper.cpp")

        assert caps["model"]["devices"]["mps"]["enabled"] is True


def test_detect_runtime_capabilities_whisper_cpp_not_macos():
    """Test detect_runtime_capabilities disables MPS on non-macOS."""
    with patch("whisper_local.transcribe.WhisperModel", None), \
         patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value="/usr/bin/whisper-cli"), \
         patch("whisper_local.transcribe._supported_compute_types", return_value=[]), \
         patch("whisper_local.transcribe.sys.platform", "linux"):

        caps = detect_runtime_capabilities("whisper.cpp")

        assert caps["model"]["devices"]["mps"]["enabled"] is False
        assert "macOS only" in caps["model"]["devices"]["mps"]["reason"]


def test_ensure_whisper_cpp_installed_success():
    """Test ensure_whisper_cpp_installed passes when installed."""
    with patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value="/usr/bin/whisper-cli"):
        # Should not raise
        ensure_whisper_cpp_installed()


def test_ensure_whisper_cpp_installed_missing():
    """Test ensure_whisper_cpp_installed raises when not installed."""
    with patch("whisper_local.transcribe._resolve_whisper_cpp_binary", return_value=None):
        with pytest.raises(RuntimeError, match="whisper.cpp is required"):
            ensure_whisper_cpp_installed()


def test_resample_audio_same_rate():
    """Test resample_audio returns original when rates match."""
    audio = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    result = resample_audio(audio, 16000, 16000)
    np.testing.assert_array_equal(result, audio)


def test_resample_audio_upsample():
    """Test resample_audio upsamples correctly."""
    audio = np.array([0.0, 1.0], dtype=np.float32)
    result = resample_audio(audio, 8000, 16000)
    assert len(result) == 4
    assert result.dtype == np.float32


def test_resample_audio_downsample():
    """Test resample_audio downsamples correctly."""
    audio = np.array([0.0, 0.5, 1.0, 0.5], dtype=np.float32)
    result = resample_audio(audio, 16000, 8000)
    assert len(result) == 2
    assert result.dtype == np.float32


def test_resample_audio_multidimensional():
    """Test resample_audio flattens multidimensional audio."""
    audio = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
    result = resample_audio(audio, 16000, 8000)
    assert result.ndim == 1


def test_resample_audio_empty_result():
    """Test resample_audio handles very short audio."""
    audio = np.array([0.1], dtype=np.float32)
    result = resample_audio(audio, 48000, 16000)
    assert len(result) == 0


def test_resolve_faster_runtime_mps_fallback():
    """Test _resolve_faster_runtime falls back from MPS to CPU."""
    from whisper_local.transcribe import _resolve_faster_runtime

    with patch("whisper_local.transcribe.logger"):
        device, compute = _resolve_faster_runtime("mps", "int8")
        assert device == "cpu"
        assert compute == "int8"


def test_resolve_faster_runtime_cpu_float16_fallback():
    """Test _resolve_faster_runtime falls back from float16 to int8 on CPU."""
    from whisper_local.transcribe import _resolve_faster_runtime

    with patch("whisper_local.transcribe.logger"):
        device, compute = _resolve_faster_runtime("cpu", "float16")
        assert device == "cpu"
        assert compute == "int8"


def test_resolve_faster_runtime_cuda_float16():
    """Test _resolve_faster_runtime keeps float16 on CUDA."""
    from whisper_local.transcribe import _resolve_faster_runtime

    device, compute = _resolve_faster_runtime("cuda", "float16")
    assert device == "cuda"
    assert compute == "float16"


def test_resolve_whispercpp_device_mps_macos():
    """Test _resolve_whispercpp_device returns mps on macOS."""
    from whisper_local.transcribe import _resolve_whispercpp_device

    with patch("whisper_local.transcribe.sys.platform", "darwin"):
        device = _resolve_whispercpp_device("mps")
        assert device == "mps"


def test_resolve_whispercpp_device_mps_linux():
    """Test _resolve_whispercpp_device falls back from mps on Linux."""
    from whisper_local.transcribe import _resolve_whispercpp_device

    with patch("whisper_local.transcribe.sys.platform", "linux"), \
         patch("whisper_local.transcribe.logger"):
        device = _resolve_whispercpp_device("mps")
        assert device == "cpu"


def test_resolve_whispercpp_device_cuda_fallback():
    """Test _resolve_whispercpp_device falls back from CUDA."""
    from whisper_local.transcribe import _resolve_whispercpp_device

    with patch("whisper_local.transcribe.logger"):
        device = _resolve_whispercpp_device("cuda")
        assert device == "cpu"


def test_resolve_whisper_cpp_binary_finds_first():
    """Test _resolve_whisper_cpp_binary finds first available binary."""
    from whisper_local.transcribe import _resolve_whisper_cpp_binary

    with patch("shutil.which") as mock_which:
        mock_which.side_effect = lambda x: "/usr/bin/whisper-cli" if x == "whisper-cli" else None
        binary = _resolve_whisper_cpp_binary()
        assert binary == "/usr/bin/whisper-cli"


def test_resolve_whisper_cpp_binary_not_found():
    """Test _resolve_whisper_cpp_binary returns None when not found."""
    from whisper_local.transcribe import _resolve_whisper_cpp_binary

    with patch("shutil.which", return_value=None):
        binary = _resolve_whisper_cpp_binary()
        assert binary is None


def test_detect_whisper_cpp_gpu_control_no_gpu_flag():
    """Test _detect_whisper_cpp_gpu_control detects no-gpu flag."""
    from whisper_local.transcribe import _detect_whisper_cpp_gpu_control

    with patch("subprocess.run") as mock_run:
        mock_result = Mock()
        mock_result.stdout = "--no-gpu  disable GPU"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        mode = _detect_whisper_cpp_gpu_control("/usr/bin/whisper-cli")
        assert mode == "no-gpu"


def test_detect_whisper_cpp_gpu_control_ng_flag():
    """Test _detect_whisper_cpp_gpu_control detects -ng flag."""
    from whisper_local.transcribe import _detect_whisper_cpp_gpu_control

    with patch("subprocess.run") as mock_run:
        mock_result = Mock()
        mock_result.stdout = "-ng  no GPU"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        mode = _detect_whisper_cpp_gpu_control("/usr/bin/whisper-cli")
        assert mode == "no-gpu"


def test_detect_whisper_cpp_gpu_control_unknown():
    """Test _detect_whisper_cpp_gpu_control returns unknown when flags not found."""
    from whisper_local.transcribe import _detect_whisper_cpp_gpu_control

    with patch("subprocess.run") as mock_run:
        mock_result = Mock()
        mock_result.stdout = "other flags"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        mode = _detect_whisper_cpp_gpu_control("/usr/bin/whisper-cli")
        assert mode == "unknown"


def test_detect_whisper_cpp_gpu_control_error():
    """Test _detect_whisper_cpp_gpu_control handles subprocess errors."""
    from whisper_local.transcribe import _detect_whisper_cpp_gpu_control

    with patch("subprocess.run", side_effect=Exception("Command failed")):
        mode = _detect_whisper_cpp_gpu_control("/usr/bin/whisper-cli")
        assert mode == "unknown"


def test_write_wav_mono16():
    """Test _write_wav_mono16 writes correct WAV file."""
    from whisper_local.transcribe import _write_wav_mono16
    import tempfile
    import wave

    audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = Path(f.name)

    try:
        _write_wav_mono16(path, audio, 16000)

        with wave.open(str(path), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getframerate() == 16000
            assert wav.getnframes() == 5
    finally:
        path.unlink()


def test_write_wav_mono16_multidimensional():
    """Test _write_wav_mono16 handles multidimensional input."""
    from whisper_local.transcribe import _write_wav_mono16
    import tempfile

    audio = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = Path(f.name)

    try:
        _write_wav_mono16(path, audio, 16000)
        assert path.exists()
    finally:
        path.unlink()


def test_to_float32_already_float32():
    """Test _to_float32 returns array unchanged if already float32."""
    from whisper_local.transcribe import _to_float32

    audio = np.array([0.1, 0.2], dtype=np.float32)
    result = _to_float32(audio)
    assert result is audio


def test_to_float32_converts_int16():
    """Test _to_float32 converts int16 to float32."""
    from whisper_local.transcribe import _to_float32

    audio = np.array([100, 200], dtype=np.int16)
    result = _to_float32(audio)
    assert result.dtype == np.float32


def test_to_float32_flattens():
    """Test _to_float32 flattens multidimensional arrays."""
    from whisper_local.transcribe import _to_float32

    audio = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
    result = _to_float32(audio)
    assert result.ndim == 1
    assert len(result) == 4


def test_subprocess_transcribe_script_constant_exists():
    """Test that _SUBPROCESS_TRANSCRIBE_SCRIPT constant is defined."""
    from whisper_local.transcribe import _SUBPROCESS_TRANSCRIBE_SCRIPT

    assert isinstance(_SUBPROCESS_TRANSCRIBE_SCRIPT, str)
    assert "WhisperModel" in _SUBPROCESS_TRANSCRIBE_SCRIPT
    assert "json" in _SUBPROCESS_TRANSCRIBE_SCRIPT
