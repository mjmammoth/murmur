from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from murmur.vad import VadProcessor, VadResult, _float_to_int16, _frame_audio


# ---------------------------------------------------------------------------
# _float_to_int16
# ---------------------------------------------------------------------------

def test_float_to_int16_clips_and_scales():
    audio = np.array([-2.0, -1.0, 0.0, 0.5, 1.0, 1.5], dtype=np.float32)
    result = _float_to_int16(audio)
    assert result.dtype == np.int16
    assert result[0] == -32767  # clipped from -2.0
    assert result[1] == -32767
    assert result[2] == 0
    assert result[4] == 32767
    assert result[5] == 32767  # clipped from 1.5


# ---------------------------------------------------------------------------
# _frame_audio
# ---------------------------------------------------------------------------

def test_frame_audio_short_returns_empty():
    audio = np.zeros(10, dtype=np.int16)
    assert _frame_audio(audio, frame_size=20) == []


def test_frame_audio_exact_frames():
    audio = np.arange(30, dtype=np.int16)
    frames = _frame_audio(audio, frame_size=10)
    assert len(frames) == 3
    np.testing.assert_array_equal(frames[0], np.arange(10, dtype=np.int16))


def test_frame_audio_partial_trailing_dropped():
    audio = np.arange(25, dtype=np.int16)
    frames = _frame_audio(audio, frame_size=10)
    assert len(frames) == 2


# ---------------------------------------------------------------------------
# VadProcessor(enabled=False)
# ---------------------------------------------------------------------------

def test_vad_disabled_passthrough():
    proc = VadProcessor(enabled=False, aggressiveness=2)
    audio = np.ones(100, dtype=np.float32)
    result = proc.trim(audio, sample_rate=16000)
    assert isinstance(result, VadResult)
    assert result.applied is False
    assert result.available is False
    np.testing.assert_array_equal(result.audio, audio)


# ---------------------------------------------------------------------------
# VadProcessor._load — ImportError path
# ---------------------------------------------------------------------------

def test_vad_load_import_error():
    with patch.dict("sys.modules", {"webrtcvad": None}):
        proc = VadProcessor(enabled=True, aggressiveness=2)
    assert proc.enabled is False
    assert proc._vad is None


# ---------------------------------------------------------------------------
# VadProcessor.trim — branches
# ---------------------------------------------------------------------------

def test_trim_disabled():
    proc = VadProcessor(enabled=False, aggressiveness=2)
    audio = np.ones(100, dtype=np.float32)
    result = proc.trim(audio, 16000)
    assert result.applied is False


def test_trim_no_vad_object():
    proc = VadProcessor(enabled=False, aggressiveness=2)
    proc.enabled = True  # force enabled but no _vad
    result = proc.trim(np.ones(100, dtype=np.float32), 16000)
    assert result.applied is False
    assert result.available is False


def test_trim_bad_sample_rate():
    proc = VadProcessor(enabled=False, aggressiveness=2)
    proc.enabled = True
    proc._vad = MagicMock()
    result = proc.trim(np.ones(100, dtype=np.float32), 22050)
    assert result.applied is False
    assert result.available is True


def test_trim_empty_audio():
    proc = VadProcessor(enabled=False, aggressiveness=2)
    proc.enabled = True
    proc._vad = MagicMock()
    result = proc.trim(np.empty(0, dtype=np.float32), 16000)
    assert result.applied is False


def test_trim_all_silence():
    proc = VadProcessor(enabled=False, aggressiveness=2)
    proc.enabled = True
    proc._vad = MagicMock()
    proc._vad.is_speech.return_value = False
    audio = np.zeros(16000, dtype=np.float32)  # 1 second at 16kHz
    result = proc.trim(audio, 16000)
    assert result.applied is True
    assert result.audio.size == 0


def test_trim_speech_present():
    proc = VadProcessor(enabled=False, aggressiveness=2)
    proc.enabled = True
    proc._vad = MagicMock()
    # Create enough audio for multiple frames at 16kHz with 30ms frames (480 samples)
    audio = np.ones(480 * 5, dtype=np.float32)
    # Middle frames have speech
    proc._vad.is_speech.side_effect = [False, True, True, False, False]
    result = proc.trim(audio, 16000)
    assert result.applied is True
    assert result.audio.size == 480 * 2  # frames 1 and 2
