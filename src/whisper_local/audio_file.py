from __future__ import annotations

from pathlib import Path

import numpy as np


DEFAULT_DECODE_SAMPLE_RATE = 16000


def load_audio_file(path: Path, target_sample_rate: int) -> np.ndarray:
    """Decode an audio file to mono float32 audio at target_sample_rate."""
    resolved = path.expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"Audio file not found: {resolved}")
    if not resolved.is_file():
        raise RuntimeError(f"Path is not a file: {resolved}")

    decode_sample_rate = (
        target_sample_rate if target_sample_rate > 0 else DEFAULT_DECODE_SAMPLE_RATE
    )

    try:
        from faster_whisper.audio import decode_audio  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Audio file decoding unavailable. Install faster-whisper."
        ) from exc

    try:
        audio = decode_audio(str(resolved), sampling_rate=decode_sample_rate)
    except TypeError:
        # Older faster-whisper versions decode at 16kHz only.
        audio = decode_audio(str(resolved))
        if decode_sample_rate != DEFAULT_DECODE_SAMPLE_RATE:
            audio = _resample_audio(
                np.asarray(audio),
                original_rate=DEFAULT_DECODE_SAMPLE_RATE,
                target_rate=decode_sample_rate,
            )
    except Exception as exc:
        raise RuntimeError(f"Unable to decode audio file {resolved}: {exc}") from exc

    array = np.asarray(audio)
    if array.ndim > 1:
        array = array.reshape(-1)
    if array.dtype != np.float32:
        array = array.astype(np.float32)
    return array


def _resample_audio(audio: np.ndarray, original_rate: int, target_rate: int) -> np.ndarray:
    if audio.ndim > 1:
        audio = np.asarray(audio).reshape(-1)
    if original_rate == target_rate:
        return audio.astype(np.float32, copy=False)
    if audio.size == 0:
        return np.empty(0, dtype=np.float32)

    duration = audio.shape[0] / float(original_rate)
    target_length = int(duration * target_rate)
    if target_length <= 1:
        return np.empty(0, dtype=np.float32)

    source_indices = np.linspace(0, 1, num=audio.shape[0], endpoint=False)
    target_indices = np.linspace(0, 1, num=target_length, endpoint=False)
    return np.interp(target_indices, source_indices, audio).astype(np.float32)
