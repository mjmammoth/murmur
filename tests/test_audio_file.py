from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from murmur.audio_file import _resample_audio, load_audio_file


# ---------------------------------------------------------------------------
# load_audio_file
# ---------------------------------------------------------------------------

def test_load_audio_file_not_found(tmp_path: Path):
    missing = tmp_path / "nonexistent.wav"
    with pytest.raises(FileNotFoundError, match="not found"):
        load_audio_file(missing, target_sample_rate=16000)


def test_load_audio_file_path_is_directory(tmp_path: Path):
    with pytest.raises(RuntimeError, match="not a file"):
        load_audio_file(tmp_path, target_sample_rate=16000)


def test_load_audio_file_faster_whisper_not_installed(tmp_path: Path):
    f = tmp_path / "test.wav"
    f.write_bytes(b"dummy")
    with patch.dict("sys.modules", {"faster_whisper": None, "faster_whisper.audio": None}):
        with pytest.raises(RuntimeError, match="Audio file decoding unavailable"):
            load_audio_file(f, target_sample_rate=16000)


def test_load_audio_file_with_sampling_rate_param(tmp_path: Path):
    f = tmp_path / "test.wav"
    f.write_bytes(b"dummy")
    raw = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    def fake_decode(path, sampling_rate=None):
        return raw

    fake_mod = types.ModuleType("faster_whisper.audio")
    fake_mod.decode_audio = fake_decode
    with patch.dict("sys.modules", {
        "faster_whisper": types.ModuleType("faster_whisper"),
        "faster_whisper.audio": fake_mod,
    }):
        result = load_audio_file(f, target_sample_rate=16000)
    np.testing.assert_array_almost_equal(result, raw)
    assert result.dtype == np.float32


def test_load_audio_file_old_api_no_sampling_rate(tmp_path: Path):
    f = tmp_path / "test.wav"
    f.write_bytes(b"dummy")
    raw = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    def fake_decode(path):
        return raw

    fake_mod = types.ModuleType("faster_whisper.audio")
    fake_mod.decode_audio = fake_decode
    with patch.dict("sys.modules", {
        "faster_whisper": types.ModuleType("faster_whisper"),
        "faster_whisper.audio": fake_mod,
    }):
        # target_sample_rate=16000 matches DEFAULT so no resample needed
        result = load_audio_file(f, target_sample_rate=16000)
    np.testing.assert_array_almost_equal(result, raw)


def test_load_audio_file_old_api_with_resample(tmp_path: Path):
    f = tmp_path / "test.wav"
    f.write_bytes(b"dummy")
    raw = np.zeros(16000, dtype=np.float32)  # 1 second at 16kHz

    def fake_decode(path):
        return raw

    fake_mod = types.ModuleType("faster_whisper.audio")
    fake_mod.decode_audio = fake_decode
    with patch.dict("sys.modules", {
        "faster_whisper": types.ModuleType("faster_whisper"),
        "faster_whisper.audio": fake_mod,
    }):
        result = load_audio_file(f, target_sample_rate=48000)
    # Should have been resampled from 16kHz to 48kHz
    assert result.dtype == np.float32
    assert result.shape[0] == 48000


def test_load_audio_file_decode_failure(tmp_path: Path):
    f = tmp_path / "test.wav"
    f.write_bytes(b"dummy")

    def fake_decode(path, sampling_rate=None):
        raise RuntimeError("decode failed")

    fake_mod = types.ModuleType("faster_whisper.audio")
    fake_mod.decode_audio = fake_decode
    with patch.dict("sys.modules", {
        "faster_whisper": types.ModuleType("faster_whisper"),
        "faster_whisper.audio": fake_mod,
    }):
        with pytest.raises(RuntimeError, match="Unable to decode"):
            load_audio_file(f, target_sample_rate=16000)


def test_load_audio_file_normalizes_multidim(tmp_path: Path):
    f = tmp_path / "test.wav"
    f.write_bytes(b"dummy")
    raw = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float64)

    def fake_decode(path, sampling_rate=None):
        return raw

    fake_mod = types.ModuleType("faster_whisper.audio")
    fake_mod.decode_audio = fake_decode
    with patch.dict("sys.modules", {
        "faster_whisper": types.ModuleType("faster_whisper"),
        "faster_whisper.audio": fake_mod,
    }):
        result = load_audio_file(f, target_sample_rate=16000)
    assert result.ndim == 1
    assert result.dtype == np.float32
    assert result.shape[0] == 4


# ---------------------------------------------------------------------------
# _resample_audio
# ---------------------------------------------------------------------------

def test_resample_same_rate():
    audio = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    result = _resample_audio(audio, 16000, 16000)
    np.testing.assert_array_equal(result, audio)


def test_resample_empty_audio():
    audio = np.empty(0, dtype=np.float32)
    result = _resample_audio(audio, 16000, 48000)
    assert result.size == 0
    assert result.dtype == np.float32


def test_resample_falls_back_to_interp_without_scipy():
    audio = np.ones(16000, dtype=np.float32)
    with patch.dict("sys.modules", {"scipy": None, "scipy.signal": None}):
        result = _resample_audio(audio, 16000, 48000)
    assert result.dtype == np.float32
    assert result.shape[0] == 48000


def test_resample_multidim_input():
    audio = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    with patch.dict("sys.modules", {"scipy": None, "scipy.signal": None}):
        result = _resample_audio(audio, 16000, 32000)
    assert result.ndim == 1
    assert result.dtype == np.float32
