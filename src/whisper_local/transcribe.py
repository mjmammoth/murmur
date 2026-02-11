from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
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
        logger.info("Loading model: %s", model_source)
        self._model = WhisperModel(model_source, device=self.device, compute_type=self.compute_type)

    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str | None = None) -> TranscriptionResult:
        if self._model is None:
            self.load()
        if self._model is None:
            raise RuntimeError("Model failed to load")
        audio = _to_float32(audio)
        if sample_rate != 16000:
            audio = resample_audio(audio, sample_rate, 16000)

        segments, info = self._model.transcribe(audio, language=language)
        text = "".join(segment.text for segment in segments).strip()
        return TranscriptionResult(text=text, language=info.language)


def resample_audio(audio: np.ndarray, original_rate: int, target_rate: int) -> np.ndarray:
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
    if audio.dtype != np.float32:
        return audio.astype(np.float32)
    return audio
