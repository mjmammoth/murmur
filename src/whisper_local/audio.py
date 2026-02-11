from __future__ import annotations

import logging
from typing import Iterable

import numpy as np
import sounddevice as sd


logger = logging.getLogger(__name__)


class AudioRecorder:
    def __init__(self, sample_rate: int, channels: int = 1, device: int | None = None) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self._stream: sd.InputStream | None = None
        self._frames: list[np.ndarray] = []

    def start(self) -> None:
        if self._stream is not None:
            return
        self._frames = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            device=self.device,
            callback=self._on_audio,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is None:
            return np.empty(0, dtype=np.float32)
        self._stream.stop()
        self._stream.close()
        self._stream = None
        return _flatten_frames(self._frames, self.channels)

    def is_recording(self) -> bool:
        return self._stream is not None

    def _on_audio(
        self,
        indata: np.ndarray,
        frames: int,
        time: sd.CallbackFlags,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.warning("Audio callback status: %s", status)
        self._frames.append(indata.copy())


def _flatten_frames(frames: Iterable[np.ndarray], channels: int) -> np.ndarray:
    if not frames:
        return np.empty(0, dtype=np.float32)
    audio = np.concatenate(list(frames), axis=0)
    if channels > 1:
        audio = audio[:, 0]
    return audio.astype(np.float32, copy=False)
