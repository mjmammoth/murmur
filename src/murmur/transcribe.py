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
    WhisperModel = None

try:  # pragma: no cover - optional runtime import
    import ctranslate2
except Exception:  # pragma: no cover - optional runtime import
    ctranslate2 = None

from murmur.config import RUNTIME_FASTER_WHISPER, RUNTIME_WHISPER_CPP, normalize_runtime_name
from murmur.model_manager import (
    get_installed_model_path,
)


logger = logging.getLogger(__name__)
WHISPER_CPP_BINARIES = ("whisper-cli", "whisper-cpp", "main")
APP_HOME = Path(os.environ.get("MURMUR_HOME", "~/.local/share/murmur")).expanduser()


def _secure_temp_root(base_dir: Path | None = None) -> Path:
    temp_root = (base_dir or APP_HOME).expanduser() / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        temp_root.chmod(0o700)
    except OSError:
        # Windows may not support POSIX chmod semantics; best effort is enough here.
        pass
    return temp_root


@dataclass
class TranscriptionResult:
    text: str
    language: str | None


class _RuntimeBase(ABC):
    runtime_name = "unknown"

    @abstractmethod
    def load(self) -> None:
        """
        Load and initialize the runtime and its model so the runtime is ready to transcribe audio.

        Implementations should allocate or open any required resources and ensure that subsequent calls to transcribe succeed. This method may be called multiple times; implementations may make it idempotent.
        """
        raise NotImplementedError

    @abstractmethod
    def transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None = None
    ) -> TranscriptionResult:
        raise NotImplementedError

    def runtime_info(self) -> dict[str, str]:
        """
        Provide metadata about the runtime's current configuration.

        Returns:
            info (dict[str, str]): A dictionary with keys:
                - "runtime": The runtime name (e.g., "faster-whisper" or "whisper.cpp").
                - "effective_device": The device actually used (e.g., "cpu", "cuda", "mps", or "unknown").
                - "effective_compute_type": The compute type in use (e.g., "int8", "float32", or "unknown").
                - "model_source": The resolved model path or identifier, or "unknown" if not set.
        """
        return {
            "runtime": self.runtime_name,
            "effective_device": "unknown",
            "effective_compute_type": "unknown",
            "model_source": "unknown",
        }


class FasterWhisperRuntime(_RuntimeBase):
    runtime_name = RUNTIME_FASTER_WHISPER

    def __init__(
        self,
        model_name: str,
        device: str,
        compute_type: str,
        model_path: str | None = None,
    ) -> None:
        """
        Initialize a FasterWhisperRuntime instance with model selection and runtime preferences.

        Parameters:
            model_name (str): Identifier of the model to load or look up when resolving a model path.
            device (str): Preferred device for inference (e.g., "cpu", "cuda", "mps"); may be adjusted when loading.
            compute_type (str): Preferred compute precision/type (e.g., "int8", "float32"); may be adjusted when loading.
            model_path (str | None): Optional filesystem path to a local model file or directory; if omitted, the installed model path for `model_name` will be searched.
        """
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_path = model_path
        self._model = None
        self._effective_device = "cpu"
        self._effective_compute_type = "int8"
        self._model_source: str | None = None

    def _resolve_model_source(self) -> str:
        """
        Determine the filesystem path to the model to load.

        Checks an explicit model_path first; if not provided, looks up an installed model path for the configured runtime.

        Returns:
            The filesystem path to the model as a string.

        Raises:
            RuntimeError: If no installed model is found for the given model_name and runtime and model_path was not provided.
        """
        if self.model_path:
            return self.model_path
        local_path = get_installed_model_path(self.model_name, runtime=self.runtime_name)
        if local_path is None:
            raise RuntimeError(
                f"Model {self.model_name} ({self.runtime_name}) is not installed"
            )
        return str(local_path)

    def load(self) -> None:
        """
        Ensure the faster-whisper model is initialized and ready for transcription.

        If the model is not already loaded, resolves the model source, determines the effective device
        and compute type, updates the instance's model-related attributes (model_path, _effective_device,
        _effective_compute_type, _model_source) and instantiates the WhisperModel.

        Raises:
            RuntimeError: If the faster-whisper runtime is not available (faster-whisper package not installed).
        """
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
        self, audio: np.ndarray, language: str | None, timeout: float = 300
    ) -> TranscriptionResult:
        model_source = self._resolve_model_source()
        device, compute_type = _resolve_faster_runtime(self.device, self.compute_type)
        cmd = [
            sys.executable,
            "-c",
            _SUBPROCESS_TRANSCRIBE_SCRIPT,
            model_source,
            device,
            compute_type,
        ]

        with tempfile.NamedTemporaryFile(
            suffix=".npy",
            delete=True,
            dir=str(_secure_temp_root()),
        ) as handle:
            np.save(handle.name, audio)
            env = os.environ.copy()
            env["HF_HUB_DISABLE_XET"] = "1"
            env["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
            run_cmd = [*cmd, handle.name, language or ""]
            try:
                result = subprocess.run(
                    run_cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = (exc.stdout or "").strip()
                stderr = (exc.stderr or "").strip()
                raise RuntimeError(
                    "Subprocess transcription timed out "
                    f"(timeout={timeout}s, command={run_cmd!r}, stdout={stdout!r}, stderr={stderr!r})"
                ) from exc
            except subprocess.CalledProcessError as exc:
                stdout = (exc.stdout or "").strip()
                stderr = (exc.stderr or "").strip()
                raise RuntimeError(
                    "Subprocess transcription failed "
                    f"(exit={exc.returncode}, command={run_cmd!r}, stderr={stderr!r}, stdout={stdout!r})"
                ) from exc

        payload = result.stdout.strip().splitlines()
        if not payload:
            raise RuntimeError("Subprocess transcription returned no output")

        parsed = json.loads(payload[-1])
        return TranscriptionResult(text=parsed.get("text", ""), language=parsed.get("language"))

    def runtime_info(self) -> dict[str, str]:
        """
        Return metadata about the active runtime and resolved model.

        Returns:
            info (dict[str, str]): Dictionary with keys:
                - "runtime": name of the runtime implementation.
                - "effective_device": device actually used (e.g., "cpu", "cuda", "mps").
                - "effective_compute_type": compute type in effect (e.g., "int8", "float32").
                - "model_source": resolved model path or the configured model identifier.
        """
        return {
            "runtime": self.runtime_name,
            "effective_device": self._effective_device,
            "effective_compute_type": self._effective_compute_type,
            "model_source": self._model_source or self.model_path or self.model_name,
        }


class WhisperCppRuntime(_RuntimeBase):
    runtime_name = RUNTIME_WHISPER_CPP

    def __init__(
        self,
        model_name: str,
        device: str,
        compute_type: str,
        model_path: str | None = None,
    ) -> None:
        """
        Create a Whisper.cpp runtime instance configured for the given model and hardware.

        Parameters:
            model_name (str): Name or identifier of the model to use.
            device (str): Requested execution device (e.g., "cpu", "mps", "cuda"); the instance will determine an effective device from this value.
            compute_type (str): Requested compute type or precision (e.g., "int8", "float32").
            model_path (str | None): Optional local path to a model file or directory; when omitted the runtime will attempt to locate an installed model.
        """
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_path = model_path
        self._binary_path: str | None = None
        self._resolved_model_path: str | None = None
        self._effective_device = _resolve_whispercpp_device(device)
        self._gpu_control_mode = "unknown"

    def load(self) -> None:
        """
        Resolve and prepare the whisper.cpp runtime and model for use by this instance.

        This locates the whisper.cpp executable, detects its GPU control mode, and resolves the model file path (either a configured local path or an installed model for this runtime). On success it sets internal fields used by transcribe: `_binary_path`, `_gpu_control_mode`, and `_resolved_model_path`, and emits an informational log entry.

        Raises:
            RuntimeError: If the whisper.cpp binary cannot be found (suggests installing whisper.cpp), if a configured local model path does not exist, if a configured model directory contains no `ggml-*.bin` files, or if the named model is not installed for this runtime.
        """
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
        """
        Transcribes the provided audio using the installed whisper.cpp executable.

        Parameters:
        	language (str | None): Optional language hint passed to whisper.cpp (e.g., language code); if None no explicit language is provided.

        Raises:
        	RuntimeError: If the whisper.cpp runtime fails to initialize or if the external whisper.cpp process exits with a non-zero status.

        Returns:
        	TranscriptionResult: Contains the transcribed `text` and the `language` value passed to this call (or `None`).
        """
        if not self._binary_path or not self._resolved_model_path:
            self.load()
        if not self._binary_path or not self._resolved_model_path:
            raise RuntimeError("whisper.cpp runtime failed to initialize")

        audio = _to_float32(audio)
        if sample_rate != 16000:
            audio = resample_audio(audio, sample_rate, 16000)

        with tempfile.TemporaryDirectory(
            prefix="murmur-whispercpp-",
            dir=str(_secure_temp_root()),
        ) as tmpdir:
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
        """
        Provide runtime metadata for this runtime implementation.

        Returns:
            info (dict[str, str]): Dictionary with the following keys:
                - "runtime": runtime identifier string.
                - "effective_device": the device actually used (e.g., "cpu", "cuda", "mps").
                - "effective_compute_type": the compute type in use (or "default" when not specified).
                - "model_source": path or identifier of the resolved model file, the configured model_path, or the original model_name.
        """
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
        runtime: str = RUNTIME_FASTER_WHISPER,
    ) -> None:
        """
        Create a Transcriber configured for a specific model and runtime.

        Initializes the transcriber with the given model name, target device, and compute type,
        optionally using a local model path, and constructs the appropriate runtime implementation.

        Parameters:
            model_name (str): The model identifier or name.
            device (str): Desired execution device (e.g., "cpu", "cuda", "mps").
            compute_type (str): Preferred compute type for the runtime (e.g., "int8", "float32").
            model_path (str | None): Optional local filesystem path to the model; if omitted the
                installed model path for the selected runtime will be used when loading.
            runtime (str): The runtime to use (normalized internally); defaults to "faster-whisper".
        """
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
        """
        Initialize and load the configured runtime and its model into memory.
        """
        self._runtime_impl.load()

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None = None
    ) -> TranscriptionResult:
        """
        Transcribe a raw audio waveform and return the transcription text and language.

        Parameters:
        	audio (np.ndarray): 1D or multi-channel audio samples.
        	sample_rate (int): Sample rate of the provided audio in Hz.
        	language (str | None): Optional language code to force transcription; if `None`, language may be detected automatically.

        Returns:
        	TranscriptionResult: Object containing the transcription `text` and the `language` (detected or the provided value).
        """
        return self._runtime_impl.transcribe(audio, sample_rate, language)

    def runtime_info(self) -> dict[str, str]:
        """
        Return combined metadata about the active runtime and the configured model.

        Returns:
            info (dict[str, str]): A mapping of runtime-related fields to their values. Contains at minimum:
                - "runtime": runtime identifier used by the transcriber implementation
                - "effective_device": the device actually used (e.g., "cpu", "cuda", "mps")
                - "effective_compute_type": the compute type selected (e.g., "int8", "float32")
                - "model_source": resolved path or source identifier for the model
                - "model_name": the model name passed to the Transcriber
        """
        info = self._runtime_impl.runtime_info()
        info["model_name"] = self.model_name
        return info


def _whisper_cpp_mps_reason(mps_enabled: bool, fallback_reason: str | None) -> str | None:
    """Return the reason string for whisper.cpp MPS device availability."""
    if mps_enabled:
        return None
    if sys.platform != "darwin":
        return "Metal acceleration is macOS only"
    return fallback_reason


def _detect_faster_whisper_capabilities() -> tuple[
    bool, str | None, dict[str, dict[str, Any]], dict[str, list[str]],
]:
    """Detect faster-whisper runtime, devices, and compute types."""
    runtime_enabled = WhisperModel is not None
    runtime_reason = None if runtime_enabled else "Python package faster-whisper is missing"

    cpu_compute = _supported_compute_types("cpu") or ["int8", "float32"]
    cuda_compute = _supported_compute_types("cuda")

    cuda_count = 0
    if ctranslate2 is not None and hasattr(ctranslate2, "get_cuda_device_count"):
        try:
            cuda_count = int(ctranslate2.get_cuda_device_count())
        except Exception:
            cuda_count = 0

    cuda_enabled = runtime_enabled and cuda_count > 0 and len(cuda_compute) > 0
    cuda_reason = _resolve_cuda_reason(
        cuda_enabled, runtime_enabled, runtime_reason, cuda_count,
    )

    devices: dict[str, dict[str, Any]] = {
        "cpu": {"enabled": runtime_enabled, "reason": runtime_reason},
        "cuda": {"enabled": cuda_enabled, "reason": cuda_reason},
        "mps": {"enabled": False, "reason": "faster-whisper uses CPU fallback for mps"},
    }
    compute = {"cpu": cpu_compute, "cuda": cuda_compute, "mps": cpu_compute}
    return runtime_enabled, runtime_reason, devices, compute


def _resolve_cuda_reason(
    cuda_enabled: bool,
    runtime_enabled: bool,
    runtime_reason: str | None,
    cuda_count: int,
) -> str | None:
    """Return the reason string explaining CUDA availability."""
    if cuda_enabled:
        return None
    if not runtime_enabled:
        return runtime_reason
    if cuda_count <= 0:
        return "No CUDA GPU detected"
    return "CTranslate2 build lacks CUDA support"


def _detect_whisper_cpp_capabilities() -> tuple[
    bool, str | None, dict[str, dict[str, Any]], dict[str, list[str]],
]:
    """Detect whisper.cpp runtime, devices, and compute types."""
    binary = _resolve_whisper_cpp_binary()
    enabled = binary is not None
    reason = (
        None if enabled
        else "whisper.cpp binary not found (install with brew install whisper-cpp)"
    )
    mps_enabled = enabled and sys.platform == "darwin"

    devices: dict[str, dict[str, Any]] = {
        "cpu": {"enabled": enabled, "reason": reason},
        "mps": {
            "enabled": mps_enabled,
            "reason": _whisper_cpp_mps_reason(mps_enabled, reason),
        },
        "cuda": {"enabled": False, "reason": "Use faster-whisper runtime for CUDA"},
    }
    compute = {"cpu": ["default"], "mps": ["default"], "cuda": []}
    return enabled, reason, devices, compute


def detect_runtime_capabilities(selected_runtime: str | None = None) -> dict[str, Any]:
    """
    Detects available transcription runtimes, their supported devices, and supported compute types.

    Parameters:
        selected_runtime (str | None): Optional runtime name to focus the returned "devices" and
            "compute_types_by_device" entries on; normalized internally. If None, defaults to
            "faster-whisper".

    Returns:
        dict: A mapping under the "model" key containing:
            - runtimes: dict mapping runtime name to {"enabled": bool, "reason": str | None}.
            - devices_by_runtime: dict mapping runtime name to per-device dicts of
              {"enabled": bool, "reason": str | None}.
            - compute_types_by_runtime_device: dict mapping runtime name to per-device lists of
              supported compute type strings.
            - devices: the per-device dict for the selected (normalized) runtime.
            - compute_types_by_device: the per-device compute-type lists for the selected runtime.
    """
    runtime_name = normalize_runtime_name(selected_runtime or RUNTIME_FASTER_WHISPER)

    faster_enabled, faster_reason, faster_devices, faster_compute = (
        _detect_faster_whisper_capabilities()
    )
    cpp_enabled, cpp_reason, cpp_devices, cpp_compute = (
        _detect_whisper_cpp_capabilities()
    )

    runtimes = {
        RUNTIME_FASTER_WHISPER: {"enabled": faster_enabled, "reason": faster_reason},
        RUNTIME_WHISPER_CPP: {"enabled": cpp_enabled, "reason": cpp_reason},
    }
    devices_by_runtime = {
        RUNTIME_FASTER_WHISPER: faster_devices,
        RUNTIME_WHISPER_CPP: cpp_devices,
    }
    compute_by_runtime_device = {
        RUNTIME_FASTER_WHISPER: faster_compute,
        RUNTIME_WHISPER_CPP: cpp_compute,
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
    """
    Verify that the whisper.cpp executable is installed and discoverable on the system PATH.

    Raises:
        RuntimeError: If no whisper.cpp binary can be located; message suggests installing via
            `brew install whisper-cpp`.
    """
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
    """
    Create a runtime implementation for the specified runtime name configured for the given model and device.

    Parameters:
        runtime (str): Normalized runtime identifier; expected values include "faster-whisper" and "whisper.cpp".
        model_name (str): Model identifier used by the runtime.
        device (str): Requested device (e.g., "cpu", "cuda", "mps"); the runtime may adjust this value.
        compute_type (str): Requested compute type (e.g., "int8", "float32"); the runtime may adjust this value.
        model_path (str | None): Optional local path to the model files; if None, the runtime will attempt to resolve an installed model.

    Returns:
        _RuntimeBase: A concrete runtime instance (WhisperCppRuntime or FasterWhisperRuntime) configured with the provided arguments.
    """
    if runtime == RUNTIME_WHISPER_CPP:
        return WhisperCppRuntime(model_name, device, compute_type, model_path)
    return FasterWhisperRuntime(model_name, device, compute_type, model_path)


def _supported_compute_types(device: str) -> list[str]:
    """
    Return the list of compute types supported for the given device.

    Parameters:
        device (str): Device identifier (for example "cpu", "cuda", or "mps").

    Returns:
        list[str]: Sorted list of supported compute type names in lowercase (e.g., ["int8", "float32"]). Returns an empty list if supported types cannot be determined or the detection capability is unavailable.
    """
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
    """
    Detects whether the specified whisper.cpp binary supports a command-line option to disable GPU.

    Parameters:
        binary_path (str): Path to the whisper.cpp executable.

    Returns:
        str: `'no-gpu'` if the binary's help text contains `--no-gpu` or `-ng`, `'unknown'` otherwise.
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

    if "--no-gpu" in help_text or "-ng" in help_text:
        return "no-gpu"
    return "unknown"


def _write_wav_mono16(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """
    Write a mono 16-bit PCM WAV file from a floating-point audio array.

    Parameters:
        path (Path): Filesystem path where the WAV file will be written.
        audio (np.ndarray): Audio samples as a 1-D or multi-dimensional float array in the range [-1.0, 1.0]. Multi-dimensional input will be flattened.
        sample_rate (int): Sample rate (frames per second) to store in the WAV header.
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
    return np.asarray(np.interp(target_indices, source_indices, audio), dtype=np.float32)


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
