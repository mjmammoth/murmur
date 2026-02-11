from __future__ import annotations

import ctypes
import ctypes.util
import logging
from dataclasses import dataclass

import numpy as np


logger = logging.getLogger(__name__)

FRAME_SIZE = 480


@dataclass
class NoiseResult:
    audio: np.ndarray
    applied: bool
    available: bool


class RNNoiseSuppressor:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.available = False
        self._lib: ctypes.CDLL | None = None
        self._state: ctypes.c_void_p | None = None
        if enabled:
            self._load()

    def _load(self) -> None:
        lib_path = ctypes.util.find_library("rnnoise")
        if not lib_path:
            logger.warning("RNNoise not found. Install with: brew install --cask rnnoise")
            return
        try:
            self._lib = ctypes.CDLL(lib_path)
        except OSError as exc:
            logger.warning("Unable to load RNNoise library: %s", exc)
            return

        self._lib.rnnoise_create.restype = ctypes.c_void_p
        self._lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
        self._lib.rnnoise_process_frame.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
        ]

        state = self._lib.rnnoise_create(None)
        if not state:
            logger.warning("Failed to initialize RNNoise state")
            return
        self._state = ctypes.c_void_p(state)
        self.available = True

    def close(self) -> None:
        if self._lib and self._state:
            self._lib.rnnoise_destroy(self._state)
        self._state = None
        self._lib = None
        self.available = False

    def process(self, audio: np.ndarray, sample_rate: int) -> NoiseResult:
        if not self.enabled:
            return NoiseResult(audio=audio, applied=False, available=self.available)
        if not self.available or self._state is None or self._lib is None:
            return NoiseResult(audio=audio, applied=False, available=False)
        if sample_rate != 48000:
            logger.warning("RNNoise requires 48kHz audio; skipping noise suppression")
            return NoiseResult(audio=audio, applied=False, available=True)

        if audio.size == 0:
            return NoiseResult(audio=audio, applied=False, available=True)

        audio = np.ascontiguousarray(audio, dtype=np.float32)
        padded = _pad_audio(audio, FRAME_SIZE)
        output = np.empty_like(padded)

        for idx in range(0, padded.shape[0], FRAME_SIZE):
            frame = padded[idx : idx + FRAME_SIZE]
            out_frame = output[idx : idx + FRAME_SIZE]
            self._lib.rnnoise_process_frame(
                self._state,
                out_frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            )

        return NoiseResult(audio=output[: audio.shape[0]], applied=True, available=True)


def _pad_audio(audio: np.ndarray, frame_size: int) -> np.ndarray:
    remainder = audio.shape[0] % frame_size
    if remainder == 0:
        return audio
    pad = frame_size - remainder
    return np.pad(audio, (0, pad), mode="constant")
