from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np


logger = logging.getLogger(__name__)

FRAME_MS = 30


@dataclass
class VadResult:
    audio: np.ndarray
    applied: bool
    available: bool


class VadProcessor:
    def __init__(self, enabled: bool, aggressiveness: int) -> None:
        self.enabled = enabled
        self.aggressiveness = aggressiveness
        self._vad = None
        if enabled:
            self._load()

    def _load(self) -> None:
        try:
            import webrtcvad
        except ImportError:
            logger.warning("webrtcvad not installed; VAD disabled")
            self._vad = None
            self.enabled = False
            return
        self._vad = webrtcvad.Vad(self.aggressiveness)

    def trim(self, audio: np.ndarray, sample_rate: int) -> VadResult:
        if not self.enabled:
            return VadResult(audio=audio, applied=False, available=bool(self._vad))
        if self._vad is None:
            return VadResult(audio=audio, applied=False, available=False)
        if sample_rate not in {8000, 16000, 32000, 48000}:
            logger.warning("Unsupported sample rate for VAD: %s", sample_rate)
            return VadResult(audio=audio, applied=False, available=True)
        if audio.size == 0:
            return VadResult(audio=audio, applied=False, available=True)

        frame_size = int(sample_rate * FRAME_MS / 1000)
        pcm = _float_to_int16(audio)
        frames = _frame_audio(pcm, frame_size)
        if not frames:
            return VadResult(audio=audio, applied=False, available=True)

        speech_flags = [self._vad.is_speech(frame.tobytes(), sample_rate) for frame in frames]
        if not any(speech_flags):
            return VadResult(audio=np.empty(0, dtype=np.float32), applied=True, available=True)

        start = speech_flags.index(True)
        end = len(speech_flags) - 1 - list(reversed(speech_flags)).index(True)
        start_idx = start * frame_size
        end_idx = min((end + 1) * frame_size, audio.shape[0])
        return VadResult(audio=audio[start_idx:end_idx], applied=True, available=True)


def _float_to_int16(audio: np.ndarray) -> np.ndarray:
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype(np.int16)


def _frame_audio(audio: np.ndarray, frame_size: int) -> list[np.ndarray]:
    if audio.shape[0] < frame_size:
        return []
    frames = []
    for idx in range(0, audio.shape[0] - frame_size + 1, frame_size):
        frames.append(audio[idx : idx + frame_size])
    return frames
