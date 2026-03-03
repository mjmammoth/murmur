from __future__ import annotations

import inspect
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
        from faster_whisper.audio import decode_audio
    except ImportError as exc:
        raise RuntimeError(
            "Audio file decoding unavailable. Install faster-whisper."
        ) from exc

    try:
        sig = inspect.signature(decode_audio)
        supports_sampling_rate = "sampling_rate" in sig.parameters
    except (ValueError, TypeError):
        supports_sampling_rate = False

    try:
        if supports_sampling_rate:
            audio = decode_audio(str(resolved), sampling_rate=decode_sample_rate)
        else:
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
    """Resample audio from original_rate to target_rate.

    Uses scipy.signal.resample_poly when available for proper anti-aliased
    resampling. Falls back to numpy linear interpolation (np.interp) which
    does NOT apply an anti-aliasing filter — this can introduce aliasing
    artifacts when downsampling. Install scipy for better quality.
    """
    if audio.ndim > 1:
        audio = np.asarray(audio).reshape(-1)
    if original_rate == target_rate:
        return audio.astype(np.float32, copy=False)
    if audio.size == 0:
        return np.empty(0, dtype=np.float32)

    from math import gcd

    common = gcd(target_rate, original_rate)
    up = target_rate // common
    down = original_rate // common

    try:
        from scipy.signal import resample_poly

        return np.asarray(resample_poly(audio, up, down), dtype=np.float32)
    except ImportError:
        pass

    target_length = int(audio.shape[0] * up / down)
    if target_length <= 1:
        return np.empty(0, dtype=np.float32)

    source_indices = np.linspace(0, 1, num=audio.shape[0], endpoint=False)
    target_indices = np.linspace(0, 1, num=target_length, endpoint=False)
    return np.asarray(np.interp(target_indices, source_indices, audio), dtype=np.float32)
