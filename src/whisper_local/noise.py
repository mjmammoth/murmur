from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from dataclasses import dataclass
from pathlib import Path

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
        self._backend: str | None = None
        self._pyrnnoise = None
        if enabled:
            self._load()

    def _load(self) -> None:
        errors: list[str] = []
        for lib_path in _rnnoise_library_candidates():
            if self._try_load_ctypes(lib_path, errors):
                return

        if self._try_load_pyrnnoise(errors):
            return

        logger.warning(
            "RNNoise unavailable. Install `pyrnnoise` (recommended) or set RNNOISE_LIB "
            "to a loadable librnnoise path. Homebrew cask rnnoise installs Audio Unit/VST "
            "plugins, which are not directly loadable via ctypes. Errors: %s",
            " | ".join(errors) if errors else "none",
        )

    def _try_load_ctypes(self, lib_path: str, errors: list[str]) -> bool:
        try:
            self._lib = ctypes.CDLL(lib_path)
        except OSError as exc:
            errors.append(f"{lib_path}: {exc}")
            self._lib = None
            self._state = None
            self.available = False
            return False

        self._lib.rnnoise_create.restype = ctypes.c_void_p
        self._lib.rnnoise_create.argtypes = [ctypes.c_void_p]
        self._lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
        self._lib.rnnoise_process_frame.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
        ]

        state = self._lib.rnnoise_create(ctypes.c_void_p())
        if not state:
            errors.append(f"{lib_path}: failed to initialize RNNoise state")
            self._lib = None
            return False

        self._state = ctypes.c_void_p(state)
        self.available = True
        self._backend = "ctypes"
        logger.info("RNNoise loaded from %s", lib_path)
        return True

    def _try_load_pyrnnoise(self, errors: list[str]) -> bool:
        try:
            from pyrnnoise import RNNoise as PyRNNoise  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            errors.append(f"pyrnnoise import failed: {exc}")
            return False

        try:
            self._pyrnnoise = PyRNNoise(sample_rate=48000)
        except Exception as exc:  # pragma: no cover - optional dependency
            errors.append(f"pyrnnoise init failed: {exc}")
            self._pyrnnoise = None
            return False

        self.available = True
        self._backend = "pyrnnoise"
        logger.info("RNNoise loaded via pyrnnoise fallback")
        return True

    def close(self) -> None:
        if self._backend == "ctypes" and self._lib and self._state:
            self._lib.rnnoise_destroy(self._state)
        if self._backend == "pyrnnoise" and self._pyrnnoise is not None:
            try:
                self._pyrnnoise.reset()
            except Exception:
                pass
        self._state = None
        self._lib = None
        self._pyrnnoise = None
        self._backend = None
        self.available = False

    def process(self, audio: np.ndarray, sample_rate: int) -> NoiseResult:
        if not self.enabled:
            return NoiseResult(audio=audio, applied=False, available=self.available)
        if not self.available or self._state is None or self._lib is None:
            if self._backend != "pyrnnoise":
                return NoiseResult(audio=audio, applied=False, available=False)
        if sample_rate != 48000:
            logger.warning("RNNoise requires 48kHz audio; skipping noise suppression")
            return NoiseResult(audio=audio, applied=False, available=True)

        if audio.size == 0:
            return NoiseResult(audio=audio, applied=False, available=True)

        if self._backend == "pyrnnoise":
            return self._process_pyrnnoise(audio)

        assert self._lib is not None
        assert self._state is not None
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

    def _process_pyrnnoise(self, audio: np.ndarray) -> NoiseResult:
        if self._pyrnnoise is None:
            return NoiseResult(audio=audio, applied=False, available=False)

        int16_audio = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        chunk = np.ascontiguousarray(int16_audio).reshape(1, -1)
        frames = []
        for _, denoised in self._pyrnnoise.denoise_chunk(chunk, partial=True):
            frames.append(denoised)
        if not frames:
            return NoiseResult(audio=audio, applied=False, available=True)
        merged = np.concatenate(frames, axis=1).reshape(-1)
        output = (merged.astype(np.float32) / 32767.0)[: audio.shape[0]]
        return NoiseResult(audio=output, applied=True, available=True)


def _pad_audio(audio: np.ndarray, frame_size: int) -> np.ndarray:
    remainder = audio.shape[0] % frame_size
    if remainder == 0:
        return audio
    pad = frame_size - remainder
    return np.pad(audio, (0, pad), mode="constant")


def _resolve_rnnoise_library_path() -> str | None:
    env_path = os.environ.get("RNNOISE_LIB")
    if env_path and Path(env_path).exists():
        return env_path

    lib_path = ctypes.util.find_library("rnnoise")
    if lib_path:
        return lib_path

    for candidate in _candidate_rnnoise_paths():
        if candidate.exists():
            return str(candidate)
    return None


def _rnnoise_library_candidates() -> list[str]:
    """
    Gather candidate filesystem or linker names for the RNNoise shared library in search order.
    
    The list includes: the RNNOISE_LIB environment variable (if set), the result of ctypes.util.find_library("rnnoise") (if any), and platform-specific candidate paths returned by _candidate_rnnoise_paths(); duplicate entries are removed while preserving their original order.
    
    Returns:
        list[str]: Ordered, deduplicated candidate paths or library names to try when locating the RNNoise library.
    """
    candidates: list[str] = []
    env_path = os.environ.get("RNNOISE_LIB")
    if env_path:
        candidates.append(env_path)

    found = ctypes.util.find_library("rnnoise")
    if found:
        candidates.append(found)

    for candidate_path in _candidate_rnnoise_paths():
        candidates.append(str(candidate_path))

    # Keep order but remove duplicates.
    deduped: list[str] = []
    seen = set()
    for candidate_name in candidates:
        if candidate_name in seen:
            continue
        seen.add(candidate_name)
        deduped.append(candidate_name)
    return deduped


def _candidate_rnnoise_paths() -> list[Path]:
    candidates = [
        Path.home() / "Library/Audio/Plug-Ins/Components/rnnoise.component/Contents/MacOS/rnnoise",
        Path("/Library/Audio/Plug-Ins/Components/rnnoise.component/Contents/MacOS/rnnoise"),
    ]

    cask_roots = [Path("/opt/homebrew/Caskroom/rnnoise"), Path("/usr/local/Caskroom/rnnoise")]
    for root in cask_roots:
        if not root.exists():
            continue
        for version_dir in sorted(root.iterdir(), reverse=True):
            candidates.append(
                version_dir / "macos-rnnoise/rnnoise.component/Contents/MacOS/rnnoise"
            )

    return candidates