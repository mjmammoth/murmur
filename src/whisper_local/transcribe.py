from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Disable HF transfer backends that can trigger FD issues in TUI/threaded runtimes.
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

from whisper_local.model_manager import (
    MODEL_NAMES,
    ensure_model_available,
    get_hf_cache_dir,
    get_installed_model_path,
)


logger = logging.getLogger(__name__)

SUPPORTED_BACKENDS = ("faster-whisper", "whisper.cpp")
WHISPER_CPP_REPO_ID = "ggerganov/whisper.cpp"
WHISPER_CPP_BINARIES = ("whisper-cli", "whisper-cpp", "main")
WHISPER_CPP_MODEL_FILES: dict[str, str] = {
    "tiny": "ggml-tiny.bin",
    "base": "ggml-base.bin",
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin",
    "large-v2": "ggml-large-v2.bin",
    "large-v3": "ggml-large-v3.bin",
}


@dataclass
class TranscriptionResult:
    text: str
    language: str | None


class _BackendBase:
    backend_name = "unknown"

    def load(self) -> None:  # pragma: no cover - interface contract
        """
        Prepare and initialize the backend for use.
        
        Implementations must perform any one-time setup required for transcription (for example: load models, initialize device/compute resources, or validate configuration). Implementations should raise an exception if initialization fails.
        """
        raise NotImplementedError

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None = None
    ) -> TranscriptionResult:  # pragma: no cover - interface contract
        """
        Transcribe the provided audio and produce a transcription result.
        
        Parameters:
            audio (np.ndarray): Audio samples (1-D or multi-channel); implementations will convert and resample as needed.
            sample_rate (int): Sample rate of `audio` in Hz.
            language (str | None): Optional ISO language tag or language hint to guide transcription.
        
        Returns:
            TranscriptionResult: Object containing the transcribed `text` and detected or used `language`.
        """
        raise NotImplementedError

    def runtime_info(self) -> dict[str, str]:
        """
        Provide basic runtime information about the backend.
        
        Returns:
            info (dict[str, str]): A dictionary with the following keys:
                - "backend": backend identifier string.
                - "effective_device": resolved device in use (e.g., "cpu", "cuda", or "unknown").
                - "effective_compute_type": resolved compute type in use (e.g., "int8", "float16", or "unknown").
                - "model_source": source identifier for the loaded model (path, model name, or "unknown").
        """
        return {
            "backend": self.backend_name,
            "effective_device": "unknown",
            "effective_compute_type": "unknown",
            "model_source": "unknown",
        }


class FasterWhisperBackend(_BackendBase):
    backend_name = "faster-whisper"

    def __init__(
        self,
        model_name: str,
        device: str,
        compute_type: str,
        model_path: str | None = None,
        auto_download: bool = True,
    ) -> None:
        """
        Initialize the FasterWhisper backend configuration.
        
        Parameters:
            model_name (str): Whisper model identifier or alias to load.
            device (str): Requested execution device (e.g., "cpu", "cuda", "mps").
            compute_type (str): Requested model compute type (e.g., "int8", "float16").
            model_path (str | None): Optional local path or directory for the model; if None, model resolution/download will be attempted later.
            auto_download (bool): If True, allow automatic download of the model when not available locally.
        
        """
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_path = model_path
        self.auto_download = auto_download
        self._model = None
        self._effective_device = "cpu"
        self._effective_compute_type = "int8"
        self._model_source: str | None = None

    def load(self) -> None:
        """
        Ensure the faster-whisper model is loaded and configured for inference.
        
        If the model is already loaded this is a no-op. Otherwise this method:
        - Resolves the model source from an explicit path, by auto-downloading, or from an installed location.
        - Determines the effective device and compute type.
        - Records the resolved model source, effective device, and compute type on the instance.
        - Instantiates and stores the WhisperModel for subsequent transcription calls.
        
        Raises:
            RuntimeError: If the faster-whisper package is unavailable.
            RuntimeError: If no model source can be resolved when auto-download is disabled.
        """
        if self._model is not None:
            return
        if WhisperModel is None:
            raise RuntimeError(
                "faster-whisper backend unavailable. Install with: python -m pip install faster-whisper"
            )

        if self.model_path:
            model_source = self.model_path
        elif self.auto_download:
            model_source = str(ensure_model_available(self.model_name))
        else:
            local_path = get_installed_model_path(self.model_name)
            if local_path is None:
                raise RuntimeError(
                    f"Model {self.model_name} is not installed and auto_download is disabled"
                )
            model_source = str(local_path)

        self.model_path = model_source
        device, compute_type = _resolve_faster_runtime(self.device, self.compute_type)
        self._effective_device = device
        self._effective_compute_type = compute_type
        self._model_source = model_source

        logger.info(
            "Loading model backend=%s model=%s source=%s device=%s compute_type=%s",
            self.backend_name,
            self.model_name,
            model_source,
            device,
            compute_type,
        )
        self._model = WhisperModel(model_source, device=device, compute_type=compute_type)

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None = None
    ) -> TranscriptionResult:
        """
        Transcribe the given audio and return the concatenated transcription and language.
        
        Attempts to load the backend model if necessary, converts audio to float32 and resamples to 16000 Hz when required, then performs transcription. If the backend raises an FD-related error (containing "fds_to_keep") the method will try to reload the model from local files and retry; if that still fails with the same FD error it falls back to a subprocess-based transcription path.
        
        Parameters:
            audio (np.ndarray): Audio samples (mono or multi-channel). Multi-channel input will be flattened/converted as part of preprocessing.
            sample_rate (int): Sample rate of the provided audio in Hz.
            language (str | None): Optional language hint or override (language code). If None, the backend may attempt language detection.
        
        Returns:
            TranscriptionResult: An object with `text` set to the concatenated transcription (stripped) and `language` set to the detected or provided language.
        
        Raises:
            RuntimeError: If the model fails to load.
            Exception: Any non-FD-related exception raised by the backend transcription is propagated.
        """
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
        """
        Reload the backend model by resolving a local model path and forcing a fresh load.
        
        If an explicit model_path is set, it is used. Otherwise, if auto_download is True the model is ensured and its local path is used; if auto_download is False the function requires an installed model and raises RuntimeError if none is found. The cached model instance is cleared and the backend load routine is invoked to initialize the model from the resolved path.
        
        Raises:
            RuntimeError: If auto_download is False and the model is not installed.
        """
        if self.model_path:
            local_path = self.model_path
        elif self.auto_download:
            local_path = str(ensure_model_available(self.model_name))
        else:
            installed_path = get_installed_model_path(self.model_name)
            if installed_path is None:
                raise RuntimeError(
                    f"Model {self.model_name} is not installed and auto_download is disabled"
                )
            local_path = str(installed_path)

        self.model_path = local_path
        self._model = None
        self.load()

    def _transcribe_in_subprocess(
        self, audio: np.ndarray, language: str | None
    ) -> TranscriptionResult:
        """
        Run transcription in a separate Python subprocess using the configured faster-whisper model and return the result.
        
        The audio is saved to a temporary .npy file and the subprocess executes an embedded transcription script with the resolved model source, device, and compute type. The subprocess is expected to print a JSON object on its last non-empty stdout line with keys `text` and `language`.
        
        Returns:
            TranscriptionResult: Contains the transcribed text and the detected language (or `None`).
        
        Raises:
            RuntimeError: If the requested model is not installed and auto_download is disabled, or if the subprocess produces no output.
            subprocess.CalledProcessError: If the subprocess exits with a non-zero status.
        """
        if self.model_path:
            model_source = self.model_path
        elif self.auto_download:
            model_source = str(ensure_model_available(self.model_name))
        else:
            installed_path = get_installed_model_path(self.model_name)
            if installed_path is None:
                raise RuntimeError(
                    f"Model {self.model_name} is not installed and auto_download is disabled"
                )
            model_source = str(installed_path)

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
        """
        Return runtime configuration details for this backend.
        
        Returns:
            info (dict[str, str]): Mapping with the following keys:
                - "backend": Backend name string.
                - "effective_device": Resolved device used at runtime (e.g., "cpu", "cuda", "mps").
                - "effective_compute_type": Resolved compute type used at runtime (e.g., "int8", "float16").
                - "model_source": Path or identifier used to load the model (local path, downloaded path, or model name).
        """
        return {
            "backend": self.backend_name,
            "effective_device": self._effective_device,
            "effective_compute_type": self._effective_compute_type,
            "model_source": self._model_source or self.model_path or self.model_name,
        }


class WhisperCppBackend(_BackendBase):
    backend_name = "whisper.cpp"

    def __init__(
        self,
        model_name: str,
        device: str,
        compute_type: str,
        model_path: str | None = None,
        auto_download: bool = True,
    ) -> None:
        """
        Initialize a Whisper.cpp backend configuration.
        
        Parameters:
            model_name (str): Model identifier (name from supported set or local model filename/directory).
            device (str): Requested device for inference (e.g., "cpu", "cuda", "mps"); the backend resolves and stores the actual effective device.
            compute_type (str): Requested compute type (not used by whisper.cpp backend; retained for API consistency).
            model_path (str | None): Optional local file or directory path to the GGML model; if omitted the backend may attempt to use a cached or downloadable model depending on `auto_download`.
            auto_download (bool): If True, allow automatic download of the model when it is not found locally.
        
        Notes:
            This constructor initializes internal state placeholders: `_binary_path`, `_resolved_model_path`, `_effective_device`, and `_gpu_control_mode`.
        """
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_path = model_path
        self.auto_download = auto_download
        self._binary_path: str | None = None
        self._resolved_model_path: str | None = None
        self._effective_device = _resolve_whispercpp_device(device)
        self._gpu_control_mode = "unknown"

    def load(self) -> None:
        """
        Prepare and validate the whisper.cpp runtime and resolve the model path for this backend.
        
        Resolves the whisper.cpp binary and its GPU control mode, validates or locates the GGML model (accepting a configured file or directory of `ggml-*.bin` files or auto-downloading a supported model), stores the resolved model path on the instance, and logs the chosen binary/model/device information.
        
        Raises:
            RuntimeError: If the whisper.cpp binary cannot be found.
            RuntimeError: If a configured local model directory contains no `ggml-*.bin` files.
            RuntimeError: If a configured local model path does not exist.
        """
        self._binary_path = _resolve_whisper_cpp_binary()
        if not self._binary_path:
            raise RuntimeError(
                "whisper.cpp backend unavailable. Install whisper.cpp (e.g. brew install whisper-cpp)"
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
            resolved = _ensure_whisper_cpp_model_available(
                self.model_name,
                auto_download=self.auto_download,
            )

        self._resolved_model_path = resolved
        logger.info(
            "Loading model backend=%s model=%s source=%s device=%s compute_type=%s binary=%s gpu_control=%s",
            self.backend_name,
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
        """
        Transcribes the provided audio using the whisper.cpp binary.
        
        Parameters:
            audio (np.ndarray): Audio samples (1-D or multi-channel); will be converted to mono and 16 kHz as needed.
            sample_rate (int): Sample rate of the input audio.
            language (str | None): Optional language code to force transcription (passed to the whisper.cpp binary).
        
        Returns:
            TranscriptionResult: Contains the transcribed `text` and the `language` value used (or `None` if not provided).
        
        Raises:
            RuntimeError: If the whisper.cpp backend failed to initialize or if the underlying whisper.cpp subprocess returns a non-zero exit code.
        """
        if not self._binary_path or not self._resolved_model_path:
            self.load()
        if not self._binary_path or not self._resolved_model_path:
            raise RuntimeError("whisper.cpp backend failed to initialize")

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

            if self._effective_device == "cpu" and self._gpu_control_mode == "no-gpu":
                cmd.append("-ng")
            elif self._gpu_control_mode == "ngl" and self._effective_device == "cpu":
                cmd.extend(["-ngl", "0"])
            elif self._gpu_control_mode == "ngl" and self._effective_device == "mps":
                cmd.extend(["-ngl", "99"])

            process = subprocess.run(cmd, capture_output=True, text=True)
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
        """
        Return runtime information for this backend instance.
        
        Provides a mapping with the following keys:
        - `backend`: backend name string.
        - `effective_device`: the resolved device used (e.g., "cpu", "cuda", "mps").
        - `effective_compute_type`: the compute type in use or `"default"` when the backend uses its default.
        - `model_source`: path or identifier for the model in use (resolved model path, explicit model_path, or model_name).
        
        Returns:
            dict[str, str]: Runtime information mapping keys to their string values.
        """
        return {
            "backend": self.backend_name,
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
        backend: str = "faster-whisper",
        auto_download: bool = True,
    ) -> None:
        """
        Initialize a Transcriber and create the selected backend implementation.
        
        Parameters:
            model_name (str): Model identifier (e.g., "small", "base") used to select or download the model.
            device (str): Desired device target (e.g., "cpu", "cuda", "mps").
            compute_type (str): Desired compute type (e.g., "int8", "float16") for the backend.
            model_path (str | None): Local path to a model file or directory; if None, model may be auto-downloaded or resolved from installed locations.
            backend (str): Preferred backend name or alias; normalized to a supported backend before creating the implementation.
            auto_download (bool): If True, allow automatic downloading of required model artifacts when not available locally.
        
        Notes:
            Initializes internal state and instantiates the concrete backend implementation used for loading and transcribing.
        """
        self.model_name = model_name
        self.backend = _normalize_backend_name(backend)
        self.device = device
        self.compute_type = compute_type
        self.model_path = model_path
        self.auto_download = auto_download
        self._backend_impl = _create_backend(
            backend=self.backend,
            model_name=model_name,
            device=device,
            compute_type=compute_type,
            model_path=model_path,
            auto_download=auto_download,
        )

    def load(self) -> None:
        """
        Initialize and load the configured backend and its model.
        """
        self._backend_impl.load()

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None = None
    ) -> TranscriptionResult:
        """
        Transcribe provided audio using the selected backend and return the transcription result.
        
        Parameters:
            audio (np.ndarray): 1-D or multi-channel audio samples (numeric array). The backend will convert to float32 and resample if needed.
            sample_rate (int): Sampling rate of `audio` in Hz.
            language (str | None): Optional ISO language code to force transcription language; pass None to auto-detect.
        
        Returns:
            TranscriptionResult: Object containing the transcribed `text` and detected or forced `language`.
        """
        return self._backend_impl.transcribe(audio, sample_rate, language)

    def runtime_info(self) -> dict[str, str]:
        """
        Return runtime information for this Transcriber, including the configured model name.
        
        Merges the selected backend's runtime info with the Transcriber's model name.
        
        Returns:
            info (dict[str, str]): Mapping of runtime information keys to string values. Always contains a "model_name" key with the Transcriber's configured model.
        """
        info = self._backend_impl.runtime_info()
        info["model_name"] = self.model_name
        return info


def detect_runtime_capabilities(selected_backend: str | None = None) -> dict[str, Any]:
    """
    Detect available transcription backends, devices, and supported compute types for the current runtime.
    
    Checks availability and reasons for the supported backends ("faster-whisper" and "whisper.cpp"), enumerates devices (cpu, cuda, mps) per backend with enablement flags and reasons, and lists supported compute types per backend/device. The returned structure also includes the selected backend's devices and compute types based on the provided or default backend.
    
    Parameters:
        selected_backend (str | None): Optional backend name or alias to query (e.g., "faster-whisper" or "whisper.cpp"). If None, defaults to the faster-whisper backend.
    
    Returns:
        dict[str, Any]: A dictionary with a top-level "model" key containing:
            - backends: mapping of backend name -> {"enabled": bool, "reason": str | None}
            - devices_by_backend: mapping of backend name -> device mappings, where each device maps to {"enabled": bool, "reason": str | None}
            - compute_types_by_backend_device: mapping of backend name -> mapping of device -> list[str] of supported compute types
            - devices: the device mapping for the selected backend (same shape as an entry in devices_by_backend)
            - compute_types_by_device: the compute-type mapping for the selected backend (same shape as an entry in compute_types_by_backend_device)
    """
    backend_name = _normalize_backend_name(selected_backend or "faster-whisper")

    faster_backend_enabled = WhisperModel is not None
    faster_backend_reason = (
        None if faster_backend_enabled else "Python package faster-whisper is missing"
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

    cuda_enabled = faster_backend_enabled and cuda_count > 0 and len(cuda_compute) > 0
    if cuda_enabled:
        cuda_reason = None
    elif not faster_backend_enabled:
        cuda_reason = faster_backend_reason
    elif cuda_count <= 0:
        cuda_reason = "No CUDA GPU detected"
    else:
        cuda_reason = "CTranslate2 build lacks CUDA support"

    faster_devices = {
        "cpu": {"enabled": faster_backend_enabled, "reason": faster_backend_reason},
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
            "reason": "Use faster-whisper backend for CUDA",
        },
    }
    whisper_cpp_compute = {
        "cpu": ["default"],
        "mps": ["default"],
        "cuda": [],
    }

    backends = {
        "faster-whisper": {
            "enabled": faster_backend_enabled,
            "reason": faster_backend_reason,
        },
        "whisper.cpp": {
            "enabled": whisper_cpp_enabled,
            "reason": whisper_cpp_reason,
        },
    }
    devices_by_backend = {
        "faster-whisper": faster_devices,
        "whisper.cpp": whisper_cpp_devices,
    }
    compute_by_backend_device = {
        "faster-whisper": faster_compute,
        "whisper.cpp": whisper_cpp_compute,
    }

    selected_devices = devices_by_backend.get(backend_name) or faster_devices
    selected_compute = compute_by_backend_device.get(backend_name) or faster_compute

    return {
        "model": {
            "backends": backends,
            "devices_by_backend": devices_by_backend,
            "compute_types_by_backend_device": compute_by_backend_device,
            "devices": selected_devices,
            "compute_types_by_device": selected_compute,
        }
    }


def ensure_whisper_cpp_installed() -> None:
    """
    Ensure the whisper.cpp CLI binary is available on the system PATH.
    
    Raises:
        RuntimeError: If no whisper.cpp binary can be located; message suggests installing via Homebrew (`brew install whisper-cpp`).
    """
    if _resolve_whisper_cpp_binary() is not None:
        return
    raise RuntimeError(
        "whisper.cpp is required but not installed. Install with: brew install whisper-cpp"
    )


def _normalize_backend_name(name: str) -> str:
    """
    Normalize a backend identifier to a canonical supported backend name.
    
    Maps known aliases for whisper.cpp (for example "whispercpp", "whisper_cpp", "whisper-cpp") to "whisper.cpp". If the input already matches a supported backend it is returned unchanged; otherwise "faster-whisper" is returned.
    
    Parameters:
        name (str): Candidate backend name or alias.
    
    Returns:
        str: Canonical backend name, either "faster-whisper" or "whisper.cpp".
    """
    normalized = (name or "").strip().lower()
    if normalized in SUPPORTED_BACKENDS:
        return normalized
    if normalized in {"whispercpp", "whisper_cpp", "whisper-cpp"}:
        return "whisper.cpp"
    return "faster-whisper"


def _create_backend(
    *,
    backend: str,
    model_name: str,
    device: str,
    compute_type: str,
    model_path: str | None,
    auto_download: bool,
) -> _BackendBase:
    """
    Create a backend implementation instance for the requested backend name.
    
    Parameters:
        backend (str): Backend identifier; use "whisper.cpp" to select the whisper.cpp backend, any other value selects the faster-whisper backend.
        model_name (str): Model name to load or reference.
        device (str): Preferred device identifier (e.g., "cpu", "cuda", "mps").
        compute_type (str): Preferred compute type (e.g., "int8", "float16").
        model_path (str | None): Optional local path to a model or model directory.
        auto_download (bool): Whether the backend may auto-download the model if not available locally.
    
    Returns:
        _BackendBase: An instance of the chosen backend configured with the provided parameters.
    """
    if backend == "whisper.cpp":
        return WhisperCppBackend(model_name, device, compute_type, model_path, auto_download)
    return FasterWhisperBackend(model_name, device, compute_type, model_path, auto_download)


def _supported_compute_types(device: str) -> list[str]:
    """
    List supported compute types for the given device as reported by ctranslate2.
    
    Parameters:
        device (str): Device identifier (e.g., "cpu", "cuda", "mps").
    
    Returns:
        list[str]: Sorted, unique, lowercase compute type names supported for the device.
            Returns an empty list if ctranslate2 is unavailable or an error occurs.
    """
    if ctranslate2 is None:
        return []
    try:
        supported = ctranslate2.get_supported_compute_types(device)
    except Exception:
        return []
    return sorted({str(item).strip().lower() for item in supported if str(item).strip()})


def _resolve_faster_runtime(requested_device: str, requested_compute_type: str) -> tuple[str, str]:
    """
    Normalize and validate a requested device and compute type for use with the faster-whisper runtime.
    
    Parameters:
    	requested_device (str): User-provided device name (e.g., "cpu", "cuda", "mps"); may contain surrounding whitespace or mixed case.
    	requested_compute_type (str): User-provided compute type (e.g., "int8", "float16", "int8_float16"); may contain surrounding whitespace or mixed case.
    
    Returns:
    	tuple[str, str]: A pair (device, compute_type) where `device` is normalized to either "cpu" or "cuda" (with "mps" mapped to "cpu"), and `compute_type` is lowercased with a default of "int8" and adjusted to "int8" when a CPU device would not benefit from float16 variants.
    """
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
    """
    Determine the effective device name to use with whisper.cpp based on a requested device.
    
    If `requested_device` is "mps" and running on macOS, returns "mps". For "mps" on non-macOS and for any "cuda" request, returns "cpu" and emits a warning indicating the fallback. Any other input returns "cpu".
    
    Parameters:
        requested_device (str): Desired device name (e.g., "cpu", "cuda", "mps").
    
    Returns:
        str: The resolved device name for whisper.cpp ("mps" or "cpu").
    """
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
    """
    Locate an installed whisper.cpp binary by checking known candidate executable names on the system PATH.
    
    Returns:
        The absolute filesystem path to the first matching binary as a `str`, or `None` if no candidate is found on PATH.
    """
    for binary in WHISPER_CPP_BINARIES:
        resolved = shutil.which(binary)
        if resolved:
            return resolved
    return None


def _detect_whisper_cpp_gpu_control(binary_path: str) -> str:
    """
    Detect which GPU-control option style a whisper.cpp binary exposes by inspecting its help text.
    
    Parameters:
        binary_path (str): Filesystem path to the whisper.cpp executable to probe.
    
    Returns:
        str: One of:
            - "no-gpu": the binary documents a `--no-gpu` (or `-ng`) option to disable GPU.
            - "ngl": the binary documents GPU-layer control options such as `--gpu-layers`, `--n-gpu-layers`, or `-ngl`.
            - "unknown": the help text did not match known patterns or probing failed.
    """
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

    if "--no-gpu" in help_text or "-ng,       --no-gpu" in help_text:
        return "no-gpu"
    if "--gpu-layers" in help_text or "--n-gpu-layers" in help_text or "-ngl" in help_text:
        return "ngl"
    return "unknown"


def _whisper_cpp_snapshots_dir() -> Path:
    """
    Get the filesystem path to the cached whisper.cpp snapshots in the Hugging Face cache.
    
    Returns:
        Path: Path to the `whisper.cpp` snapshots directory inside the HF cache (…/hub/models--ggerganov--whisper.cpp/snapshots).
    """
    return get_hf_cache_dir() / "hub" / "models--ggerganov--whisper.cpp" / "snapshots"


def _find_cached_whisper_cpp_model(filename: str) -> Path | None:
    """
    Search the whisper.cpp snapshots cache for a file with the given filename and return the most recently modified match.
    
    Looks for subdirectories under the whisper.cpp snapshots directory that contain a file named by `filename`. If one or more matches are found, returns the Path of the most recently modified match; otherwise returns `None`.
    
    Returns:
        Path | None: Path to the newest matching file if found, `None` if no match exists.
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


def _ensure_whisper_cpp_model_available(model_name: str, auto_download: bool) -> str:
    """
    Locate a local whisper.cpp ggml model file for the given model name or download it from the HF Hub if allowed, and return its filesystem path.
    
    Parameters:
        model_name (str): Name of the whisper model (must be one of supported MODEL_NAMES).
        auto_download (bool): If True, attempt to download the model from the HF Hub when not cached; if False, do not download.
    
    Returns:
        str: Absolute path to the ggml model file for the requested model.
    
    Raises:
        ValueError: If `model_name` is not recognized.
        RuntimeError: If no filename mapping exists for the model, if the model is not installed and `auto_download` is False,
                      or if downloading the model fails.
    """
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model: {model_name}")

    filename = WHISPER_CPP_MODEL_FILES.get(model_name)
    if not filename:
        raise RuntimeError(f"whisper.cpp model file mapping missing for model: {model_name}")

    cached = _find_cached_whisper_cpp_model(filename)
    if cached is not None:
        return str(cached)

    if not auto_download:
        raise RuntimeError(
            f"whisper.cpp model {model_name} is not installed and auto_download is disabled"
        )

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

    try:
        from huggingface_hub import hf_hub_download

        downloaded = hf_hub_download(repo_id=WHISPER_CPP_REPO_ID, filename=filename)
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        raise RuntimeError(f"Failed to download whisper.cpp model {model_name}: {exc}") from exc

    return str(Path(downloaded))


def _write_wav_mono16(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """
    Write a mono 16-bit PCM WAV file from a float audio array.
    
    Converts the input audio to a single-channel stream (flattening multi-dimensional arrays), clamps samples to the range -1.0 to 1.0, scales to signed 16-bit integer PCM, and writes a WAV file with the specified sample rate.
    
    Parameters:
        path (Path): Destination file path for the WAV file.
        audio (np.ndarray): Audio samples as a float array. Values are expected in the range [-1.0, 1.0]; any shape is accepted and will be flattened to mono.
        sample_rate (int): Sample rate (Hz) to set in the WAV file.
    """
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
    """
    Resample audio to a different sample rate using linear interpolation.
    
    Converts multi-channel input to a 1-D signal, resamples from original_rate to target_rate, and returns a float32 array. If original_rate equals target_rate, the input (flattened to 1-D) is returned. If the computed target length is less than or equal to 1, an empty float32 array is returned.
    
    Parameters:
        audio (np.ndarray): Audio samples; may be multi-dimensional (channels x samples or similar).
        original_rate (int): Sample rate of the input audio in Hz.
        target_rate (int): Desired sample rate in Hz.
    
    Returns:
        np.ndarray: 1-D numpy array of float32 audio samples resampled to target_rate, or an empty array if the target length is <= 1.
    """
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
    """
    Ensure an audio array is one-dimensional and has dtype float32.
    
    Parameters:
        audio (np.ndarray): Audio samples; may be multi-dimensional and any numeric dtype.
    
    Returns:
        np.ndarray: A one-dimensional `float32` array of audio samples.
    """
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