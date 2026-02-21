from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Disable HF transfer runtimes that can trigger FD issues in TUI/threaded runtimes.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

try:  # pragma: no cover - optional runtime import
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover - optional runtime import
    WhisperModel = None  # type: ignore[assignment]

try:  # pragma: no cover - optional runtime import
    import ctranslate2
except Exception:  # pragma: no cover - optional runtime import
    ctranslate2 = None  # type: ignore[assignment]

from whisper_local.config import normalize_runtime_name
from whisper_local.model_manager import (
    get_installed_model_path,
)


logger = logging.getLogger(__name__)
WHISPER_CPP_BINARIES = ("whisper-cli", "whisper-cpp", "main")


@dataclass
class TranscriptionResult:
    text: str
    language: str | None


class _RuntimeBase(ABC):
    runtime_name = "unknown"

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None = None
    ) -> TranscriptionResult:
        raise NotImplementedError

    def runtime_info(self) -> dict[str, str]:
        return {
            "runtime": self.runtime_name,
            "effective_device": "unknown",
            "effective_compute_type": "unknown",
            "model_source": "unknown",
        }


class FasterWhisperRuntime(_RuntimeBase):
    runtime_name = "faster-whisper"

    def __init__(
        self,
        model_name: str,
        device: str,
        compute_type: str,
        model_path: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_path = model_path
        self._model = None
        self._effective_device = "cpu"
        self._effective_compute_type = "int8"
        self._model_source: str | None = None

    def _resolve_model_source(self) -> str:
        """Resolve the model source path from config, cache, or download."""
        if self.model_path:
            return self.model_path
        local_path = get_installed_model_path(self.model_name, runtime=self.runtime_name)
        if local_path is None:
            raise RuntimeError(
                f"Model {self.model_name} ({self.runtime_name}) is not installed"
            )
        return str(local_path)

    def load(self) -> None:
        if self._model is not None:
            return
        if WhisperModel is None:
            raise RuntimeError(
                "faster-whisper runtime unavailable. Install with: python -m pip install faster-whisper"
            )

        model_source = self._resolve_model_source()
        self.model_path = model_source
        device, compute_type = _resolve_faster_runtime(self.device, self.compute_type)
        self._effective_device = device
        self._effective_compute_type = compute_type
        self._model_source = model_source

        logger.info(
            "Loading model runtime=%s model=%s source=%s device=%s compute_type=%s",
            self.runtime_name,
            self.model_name,
            model_source,
            device,
            compute_type,
        )
        self._model = WhisperModel(model_source, device=device, compute_type=compute_type)

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None = None
    ) -> TranscriptionResult:
        if self._model is None:
            self.load()
        if self._model is None:
            raise RuntimeError("Model failed to load")

        audio = _to_float32(audio)
        if sample_rate != 16000:
            audio = resample_audio(audio, sample_rate, 16000)

        try:
            segments, info = self._model.transcribe(audio, language=language)
        except Exception as exc:
            if "fds_to_keep" not in str(exc):
                raise
            logger.warning("Transcribe hit FD error; reloading model from local files")
            try:
                self._reload_model_from_local()
                segments, info = self._model.transcribe(audio, language=language)
            except Exception as retry_exc:
                if "fds_to_keep" not in str(retry_exc):
                    raise
                logger.warning("Transcribe still hitting FD error; falling back to subprocess")
                return self._transcribe_in_subprocess(audio, language)

        text = "".join(segment.text for segment in segments).strip()
        return TranscriptionResult(text=text, language=info.language)

    def _reload_model_from_local(self) -> None:
        self.model_path = self._resolve_model_source()
        self._model = None
        self.load()

    def _transcribe_in_subprocess(
        self, audio: np.ndarray, language: str | None
    ) -> TranscriptionResult:
        model_source = self._resolve_model_source()
        device, compute_type = _resolve_faster_runtime(self.device, self.compute_type)

        with tempfile.NamedTemporaryFile(suffix=".npy", delete=True) as handle:
            np.save(handle.name, audio)
            env = os.environ.copy()
            env["HF_HUB_DISABLE_XET"] = "1"
            env["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _SUBPROCESS_TRANSCRIBE_SCRIPT,
                    model_source,
                    device,
                    compute_type,
                    handle.name,
                    language or "",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

        payload = result.stdout.strip().splitlines()
        if not payload:
            raise RuntimeError("Subprocess transcription returned no output")

        parsed = json.loads(payload[-1])
        return TranscriptionResult(text=parsed.get("text", ""), language=parsed.get("language"))

    def runtime_info(self) -> dict[str, str]:
        return {
            "runtime": self.runtime_name,
            "effective_device": self._effective_device,
            "effective_compute_type": self._effective_compute_type,
            "model_source": self._model_source or self.model_path or self.model_name,
        }


class WhisperCppRuntime(_RuntimeBase):
    runtime_name = "whisper.cpp"

    def __init__(
        self,
        model_name: str,
        device: str,
        compute_type: str,
        model_path: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_path = model_path
        self._binary_path: str | None = None
        self._resolved_model_path: str | None = None
        self._effective_device = _resolve_whispercpp_device(device)
        self._gpu_control_mode = "unknown"

    def load(self) -> None:
        self._binary_path = _resolve_whisper_cpp_binary()
        if not self._binary_path:
            raise RuntimeError(
                "whisper.cpp runtime unavailable. Install whisper.cpp (e.g. brew install whisper-cpp)"
            )
        self._gpu_control_mode = _detect_whisper_cpp_gpu_control(self._binary_path)

        if self.model_path:
            configured_path = Path(self.model_path).expanduser()
            if configured_path.is_dir():
                candidates = sorted(configured_path.glob("ggml-*.bin"))
                if not candidates:
                    raise RuntimeError(
                        f"Local model path directory has no ggml-*.bin model files: {configured_path}"
                    )
                resolved = str(candidates[0])
            else:
                resolved = str(configured_path)

            if not Path(resolved).exists():
                raise RuntimeError(f"Configured local model path does not exist: {resolved}")
        else:
            installed_path = get_installed_model_path(
                self.model_name, runtime=self.runtime_name
            )
            if installed_path is None:
                raise RuntimeError(
                    f"Model {self.model_name} ({self.runtime_name}) is not installed"
                )
            resolved = str(installed_path)

        self._resolved_model_path = resolved
        logger.info(
            "Loading model runtime=%s model=%s source=%s device=%s compute_type=%s binary=%s gpu_control=%s",
            self.runtime_name,
            self.model_name,
            resolved,
            self._effective_device,
            "default",
            self._binary_path,
            self._gpu_control_mode,
        )

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None = None
    ) -> TranscriptionResult:
        if not self._binary_path or not self._resolved_model_path:
            self.load()
        if not self._binary_path or not self._resolved_model_path:
            raise RuntimeError("whisper.cpp runtime failed to initialize")

        audio = _to_float32(audio)
        if sample_rate != 16000:
            audio = resample_audio(audio, sample_rate, 16000)

        with tempfile.TemporaryDirectory(prefix="whisper-local-whispercpp-") as tmpdir:
            base_dir = Path(tmpdir)
            audio_path = base_dir / "audio.wav"
            output_base = base_dir / "result"
            _write_wav_mono16(audio_path, audio, 16000)

            cmd = [
                self._binary_path,
                "-m",
                self._resolved_model_path,
                "-f",
                str(audio_path),
                "-of",
                str(output_base),
                "-otxt",
                "-nt",
                "-np",
            ]

            if language:
                cmd.extend(["-l", language])

            if self._effective_device == "cpu":
                cmd.append("-ng")

            process = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if process.returncode != 0:
                stderr = (process.stderr or process.stdout or "").strip()
                raise RuntimeError(
                    f"whisper.cpp transcription failed (exit={process.returncode}): {stderr}"
                )

            txt_path = output_base.with_suffix(".txt")
            if txt_path.exists():
                text = txt_path.read_text(encoding="utf-8", errors="ignore").strip()
            else:
                text = (process.stdout or "").strip()

        return TranscriptionResult(text=text, language=language)

    def runtime_info(self) -> dict[str, str]:
        return {
            "runtime": self.runtime_name,
            "effective_device": self._effective_device,
            "effective_compute_type": "default",
            "model_source": self._resolved_model_path or self.model_path or self.model_name,
        }


class Transcriber:
    def __init__(
        self,
        model_name: str,
        device: str,
        compute_type: str,
        model_path: str | None = None,
        runtime: str = "faster-whisper",
    ) -> None:
        self.model_name = model_name
        self.runtime = normalize_runtime_name(runtime)
        self.device = device
        self.compute_type = compute_type
        self.model_path = model_path
        self._runtime_impl = _create_runtime(
            runtime=self.runtime,
            model_name=model_name,
            device=device,
            compute_type=compute_type,
            model_path=model_path,
        )

    def load(self) -> None:
        self._runtime_impl.load()

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None = None
    ) -> TranscriptionResult:
        return self._runtime_impl.transcribe(audio, sample_rate, language)

    def runtime_info(self) -> dict[str, str]:
        info = self._runtime_impl.runtime_info()
        info["model_name"] = self.model_name
        return info


def detect_runtime_capabilities(selected_runtime: str | None = None) -> dict[str, Any]:
    runtime_name = normalize_runtime_name(selected_runtime or "faster-whisper")

    faster_runtime_enabled = WhisperModel is not None
    faster_runtime_reason = (
        None if faster_runtime_enabled else "Python package faster-whisper is missing"
    )

    cpu_compute = _supported_compute_types("cpu")
    cuda_compute = _supported_compute_types("cuda")
    if not cpu_compute:
        cpu_compute = ["int8", "float32"]

    cuda_count = 0
    if ctranslate2 is not None and hasattr(ctranslate2, "get_cuda_device_count"):
        try:
            cuda_count = int(ctranslate2.get_cuda_device_count())
        except Exception:
            cuda_count = 0

    cuda_enabled = faster_runtime_enabled and cuda_count > 0 and len(cuda_compute) > 0
    if cuda_enabled:
        cuda_reason = None
    elif not faster_runtime_enabled:
        cuda_reason = faster_runtime_reason
    elif cuda_count <= 0:
        cuda_reason = "No CUDA GPU detected"
    else:
        cuda_reason = "CTranslate2 build lacks CUDA support"

    faster_devices = {
        "cpu": {"enabled": faster_runtime_enabled, "reason": faster_runtime_reason},
        "cuda": {"enabled": cuda_enabled, "reason": cuda_reason},
        "mps": {
            "enabled": False,
            "reason": "faster-whisper uses CPU fallback for mps",
        },
    }
    faster_compute = {
        "cpu": cpu_compute,
        "cuda": cuda_compute,
        "mps": cpu_compute,
    }

    whisper_cpp_binary = _resolve_whisper_cpp_binary()
    whisper_cpp_enabled = whisper_cpp_binary is not None
    whisper_cpp_reason = (
        None
        if whisper_cpp_enabled
        else "whisper.cpp binary not found (install with brew install whisper-cpp)"
    )
    whisper_cpp_mps_enabled = whisper_cpp_enabled and sys.platform == "darwin"

    whisper_cpp_devices = {
        "cpu": {"enabled": whisper_cpp_enabled, "reason": whisper_cpp_reason},
        "mps": {
            "enabled": whisper_cpp_mps_enabled,
            "reason": (
                None
                if whisper_cpp_mps_enabled
                else (
                    "Metal acceleration is macOS only"
                    if sys.platform != "darwin"
                    else whisper_cpp_reason
                )
            ),
        },
        "cuda": {
            "enabled": False,
            "reason": "Use faster-whisper runtime for CUDA",
        },
    }
    whisper_cpp_compute = {
        "cpu": ["default"],
        "mps": ["default"],
        "cuda": [],
    }

    runtimes = {
        "faster-whisper": {
            "enabled": faster_runtime_enabled,
            "reason": faster_runtime_reason,
        },
        "whisper.cpp": {
            "enabled": whisper_cpp_enabled,
            "reason": whisper_cpp_reason,
        },
    }
    devices_by_runtime = {
        "faster-whisper": faster_devices,
        "whisper.cpp": whisper_cpp_devices,
    }
    compute_by_runtime_device = {
        "faster-whisper": faster_compute,
        "whisper.cpp": whisper_cpp_compute,
    }

    selected_devices = devices_by_runtime.get(runtime_name) or faster_devices
    selected_compute = compute_by_runtime_device.get(runtime_name) or faster_compute

    return {
        "model": {
            "runtimes": runtimes,
            "devices_by_runtime": devices_by_runtime,
            "compute_types_by_runtime_device": compute_by_runtime_device,
            "devices": selected_devices,
            "compute_types_by_device": selected_compute,
        }
    }


def ensure_whisper_cpp_installed() -> None:
    """Hard runtime requirement for the CLI app package."""
    if _resolve_whisper_cpp_binary() is not None:
        return
    raise RuntimeError(
        "whisper.cpp is required but not installed. Install with: brew install whisper-cpp"
    )


def _create_runtime(
    *,
    runtime: str,
    model_name: str,
    device: str,
    compute_type: str,
    model_path: str | None,
) -> _RuntimeBase:
    if runtime == "whisper.cpp":
        return WhisperCppRuntime(model_name, device, compute_type, model_path)
    return FasterWhisperRuntime(model_name, device, compute_type, model_path)


def _supported_compute_types(device: str) -> list[str]:
    if ctranslate2 is None:
        return []
    try:
        supported = ctranslate2.get_supported_compute_types(device)
    except Exception:
        return []
    return sorted({str(item).strip().lower() for item in supported if str(item).strip()})


def _resolve_faster_runtime(requested_device: str, requested_compute_type: str) -> tuple[str, str]:
    device = requested_device.lower().strip()
    compute_type = requested_compute_type.lower().strip()

    if device == "mps":
        logger.warning("faster-whisper does not support mps directly. Falling back to cpu.")
        device = "cpu"
    if device not in {"cpu", "cuda"}:
        device = "cpu"

    if not compute_type:
        compute_type = "int8"

    if device == "cpu" and compute_type in {"float16", "int8_float16"}:
        logger.warning("CPU mode does not benefit from %s. Using int8.", compute_type)
        compute_type = "int8"

    return device, compute_type


def _resolve_whispercpp_device(requested_device: str) -> str:
    device = (requested_device or "").lower().strip()
    if device == "mps":
        if sys.platform == "darwin":
            return "mps"
        logger.warning("whisper.cpp mps is only available on macOS. Falling back to cpu.")
        return "cpu"
    if device == "cuda":
        logger.warning("whisper.cpp CUDA is not supported in this app flow. Falling back to cpu.")
    return "cpu"


def _resolve_whisper_cpp_binary() -> str | None:
    for binary in WHISPER_CPP_BINARIES:
        resolved = shutil.which(binary)
        if resolved:
            return resolved
    return None


def _detect_whisper_cpp_gpu_control(binary_path: str) -> str:
    try:
        result = subprocess.run(
            [binary_path, "-h"],
            capture_output=True,
            text=True,
            check=False,
        )
        help_text = f"{result.stdout}\n{result.stderr}"
    except Exception:
        return "unknown"

    if "--no-gpu" in help_text or "-ng" in help_text:
        return "no-gpu"
    return "unknown"


def _write_wav_mono16(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    if audio.ndim > 1:
        audio = np.asarray(audio).reshape(-1)

    clamped = np.clip(audio, -1.0, 1.0)
    pcm = (clamped * 32767.0).astype(np.int16)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def resample_audio(audio: np.ndarray, original_rate: int, target_rate: int) -> np.ndarray:
    if audio.ndim > 1:
        audio = np.asarray(audio).reshape(-1)
    if original_rate == target_rate:
        return audio
    duration = audio.shape[0] / float(original_rate)
    target_length = int(duration * target_rate)
    if target_length <= 1:
        return np.empty(0, dtype=np.float32)
    source_indices = np.linspace(0, 1, num=audio.shape[0], endpoint=False)
    target_indices = np.linspace(0, 1, num=target_length, endpoint=False)
    return np.interp(target_indices, source_indices, audio).astype(np.float32)


def _to_float32(audio: np.ndarray) -> np.ndarray:
    if audio.ndim > 1:
        audio = np.asarray(audio).reshape(-1)
    if audio.dtype != np.float32:
        return audio.astype(np.float32)
    return audio


_SUBPROCESS_TRANSCRIBE_SCRIPT = """
import json
import os
import sys
import numpy as np

os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_HUB_ENABLE_HF_TRANSFER', '0')

from faster_whisper import WhisperModel

model_source, device, compute_type, audio_path, language = sys.argv[1:6]
audio = np.load(audio_path)
model = WhisperModel(model_source, device=device, compute_type=compute_type)
segments, info = model.transcribe(audio, language=(language or None))
text = ''.join(segment.text for segment in segments).strip()
print(json.dumps({'text': text, 'language': info.language}))
"""
