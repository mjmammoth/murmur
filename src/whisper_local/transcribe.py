from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Disable HF transfer backends that can trigger FD issues in TUI/threaded runtimes.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

from faster_whisper import WhisperModel


logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    language: str | None


class Transcriber:
    def __init__(self, model_name: str, device: str, compute_type: str, model_path: str | None = None):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_path = model_path
        self._model: WhisperModel | None = None

    def load(self) -> None:
        if self._model is not None:
            return
        model_source = self.model_path or self.model_name
        device, compute_type = _resolve_runtime(self.device, self.compute_type)
        logger.info(
            "Loading model: %s (device=%s, compute_type=%s)",
            model_source,
            device,
            compute_type,
        )
        self._model = WhisperModel(model_source, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str | None = None) -> TranscriptionResult:
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
        from whisper_local.model_manager import get_installed_model_path

        local_path = self.model_path or get_installed_model_path(self.model_name)
        if local_path is None:
            raise RuntimeError(
                f"Model files for {self.model_name} are not available locally. "
                f"Run `whisper-local models pull {self.model_name}` and retry."
            )

        self.model_path = str(local_path)
        self._model = None
        self.load()

    def _transcribe_in_subprocess(self, audio: np.ndarray, language: str | None) -> TranscriptionResult:
        model_source = self._local_model_source()
        device, compute_type = _resolve_runtime(self.device, self.compute_type)

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
        import json

        parsed = json.loads(payload[-1])
        return TranscriptionResult(text=parsed.get("text", ""), language=parsed.get("language"))

    def _local_model_source(self) -> str:
        if self.model_path:
            return self.model_path
        from whisper_local.model_manager import get_installed_model_path

        local_path = get_installed_model_path(self.model_name)
        if local_path is None:
            raise RuntimeError(
                f"Model files for {self.model_name} are not available locally. "
                f"Run `whisper-local models pull {self.model_name}` and retry."
            )
        return str(local_path)


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
    resampled = np.interp(target_indices, source_indices, audio).astype(np.float32)
    return resampled


def _to_float32(audio: np.ndarray) -> np.ndarray:
    if audio.ndim > 1:
        audio = np.asarray(audio).reshape(-1)
    if audio.dtype != np.float32:
        return audio.astype(np.float32)
    return audio


def _resolve_runtime(requested_device: str, requested_compute_type: str) -> tuple[str, str]:
    device = requested_device.lower().strip()
    compute_type = requested_compute_type.lower().strip()

    if device == "mps":
        logger.warning("faster-whisper does not support mps directly. Falling back to cpu.")
        device = "cpu"

    if device == "cpu" and compute_type in {"float16", "int8_float16"}:
        logger.warning("CPU mode does not benefit from %s. Using int8.", compute_type)
        compute_type = "int8"

    return device, compute_type


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
