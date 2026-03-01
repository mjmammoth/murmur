from __future__ import annotations

import ctypes
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from murmur.noise import (
    FRAME_SIZE,
    RNNoiseSuppressor,
    _candidate_rnnoise_paths,
    _pad_audio,
    _resolve_rnnoise_library_path,
    _rnnoise_library_candidates,
)


# ---------------------------------------------------------------------------
# _pad_audio
# ---------------------------------------------------------------------------

def test_pad_audio_aligned():
    audio = np.zeros(FRAME_SIZE * 3, dtype=np.float32)
    result = _pad_audio(audio, FRAME_SIZE)
    assert result is audio  # no copy needed


def test_pad_audio_unaligned():
    audio = np.zeros(FRAME_SIZE * 2 + 100, dtype=np.float32)
    result = _pad_audio(audio, FRAME_SIZE)
    assert result.shape[0] == FRAME_SIZE * 3
    assert result.shape[0] % FRAME_SIZE == 0


# ---------------------------------------------------------------------------
# _candidate_rnnoise_paths
# ---------------------------------------------------------------------------

def test_candidate_rnnoise_paths_defaults():
    paths = _candidate_rnnoise_paths()
    assert len(paths) >= 2
    assert all(isinstance(p, Path) for p in paths)


def test_candidate_rnnoise_paths_with_caskroom(tmp_path: Path, monkeypatch):
    cask_root = tmp_path / "Caskroom" / "rnnoise"
    v1 = cask_root / "1.0"
    v2 = cask_root / "2.0"
    v1.mkdir(parents=True)
    v2.mkdir(parents=True)

    original_exists = Path.exists
    original_iterdir = Path.iterdir

    def patched_exists(path: Path) -> bool:
        if str(path) == "/opt/homebrew/Caskroom/rnnoise":
            return True
        if str(path) == "/usr/local/Caskroom/rnnoise":
            return False
        return original_exists(path)

    def patched_iterdir(path: Path):
        if str(path) == "/opt/homebrew/Caskroom/rnnoise":
            return iter([v1, v2])
        return original_iterdir(path)

    monkeypatch.setattr(Path, "exists", patched_exists)
    monkeypatch.setattr(Path, "iterdir", patched_iterdir)

    paths = _candidate_rnnoise_paths()
    assert len(paths) >= 4
    expected_v2 = v2 / "macos-rnnoise/rnnoise.component/Contents/MacOS/rnnoise"
    expected_v1 = v1 / "macos-rnnoise/rnnoise.component/Contents/MacOS/rnnoise"
    assert expected_v2 in paths
    assert expected_v1 in paths
    assert paths.index(expected_v2) < paths.index(expected_v1)


# ---------------------------------------------------------------------------
# _rnnoise_library_candidates
# ---------------------------------------------------------------------------

def test_rnnoise_library_candidates_env_var(monkeypatch):
    monkeypatch.setenv("RNNOISE_LIB", "/custom/librnnoise.dylib")
    with patch("murmur.noise.ctypes.util.find_library", return_value=None):
        candidates = _rnnoise_library_candidates()
    assert candidates[0] == "/custom/librnnoise.dylib"


def test_rnnoise_library_candidates_find_library(monkeypatch):
    monkeypatch.delenv("RNNOISE_LIB", raising=False)
    with patch("murmur.noise.ctypes.util.find_library", return_value="librnnoise.so"):
        candidates = _rnnoise_library_candidates()
    assert "librnnoise.so" in candidates


def test_rnnoise_library_candidates_deduplication(monkeypatch):
    monkeypatch.setenv("RNNOISE_LIB", "/custom/lib.dylib")
    with patch("murmur.noise.ctypes.util.find_library", return_value="/custom/lib.dylib"):
        candidates = _rnnoise_library_candidates()
    assert candidates.count("/custom/lib.dylib") == 1


# ---------------------------------------------------------------------------
# RNNoiseSuppressor(enabled=False)
# ---------------------------------------------------------------------------

def test_suppressor_disabled():
    sup = RNNoiseSuppressor(enabled=False)
    assert sup.available is False
    assert sup._backend is None


# ---------------------------------------------------------------------------
# RNNoiseSuppressor._load failure
# ---------------------------------------------------------------------------

def test_suppressor_load_all_fail(monkeypatch):
    monkeypatch.delenv("RNNOISE_LIB", raising=False)
    with patch("murmur.noise.ctypes.util.find_library", return_value=None), \
         patch("murmur.noise._candidate_rnnoise_paths", return_value=[]), \
         patch.dict("sys.modules", {"pyrnnoise": None}):
        sup = RNNoiseSuppressor(enabled=True)
    assert sup.available is False


# ---------------------------------------------------------------------------
# _try_load_ctypes
# ---------------------------------------------------------------------------

def test_try_load_ctypes_oserror():
    sup = RNNoiseSuppressor(enabled=False)
    errors: list[str] = []
    with patch("murmur.noise.ctypes.CDLL", side_effect=OSError("not found")):
        result = sup._try_load_ctypes("/fake/lib.dylib", errors)
    assert result is False
    assert len(errors) == 1


def test_try_load_ctypes_create_returns_zero():
    sup = RNNoiseSuppressor(enabled=False)
    errors: list[str] = []
    mock_lib = MagicMock()
    mock_lib.rnnoise_create.return_value = 0  # failed init
    with patch("murmur.noise.ctypes.CDLL", return_value=mock_lib):
        result = sup._try_load_ctypes("/fake/lib.dylib", errors)
    assert result is False
    assert sup._lib is None


def test_try_load_ctypes_success():
    sup = RNNoiseSuppressor(enabled=False)
    errors: list[str] = []
    mock_lib = MagicMock()
    mock_lib.rnnoise_create.return_value = 42  # valid state pointer
    with patch("murmur.noise.ctypes.CDLL", return_value=mock_lib):
        result = sup._try_load_ctypes("/fake/lib.dylib", errors)
    assert result is True
    assert sup.available is True
    assert sup._backend == "ctypes"


# ---------------------------------------------------------------------------
# _try_load_pyrnnoise
# ---------------------------------------------------------------------------

def test_try_load_pyrnnoise_success():
    sup = RNNoiseSuppressor(enabled=False)
    errors: list[str] = []
    mock_pyrnnoise_cls = MagicMock()
    mock_instance = MagicMock()
    mock_pyrnnoise_cls.return_value = mock_instance

    import types
    fake_mod = types.ModuleType("pyrnnoise")
    fake_mod.RNNoise = mock_pyrnnoise_cls
    with patch.dict("sys.modules", {"pyrnnoise": fake_mod}):
        result = sup._try_load_pyrnnoise(errors)
    assert result is True
    assert sup._backend == "pyrnnoise"


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

def test_close_ctypes_backend():
    sup = RNNoiseSuppressor(enabled=False)
    sup._backend = "ctypes"
    mock_lib = MagicMock()
    sup._lib = mock_lib
    state = ctypes.c_void_p(42)
    sup._state = state
    sup.available = True
    sup.close()
    mock_lib.rnnoise_destroy.assert_called_once_with(state)
    assert sup._lib is None
    assert sup._state is None
    assert sup.available is False


def test_close_pyrnnoise_backend():
    sup = RNNoiseSuppressor(enabled=False)
    sup._backend = "pyrnnoise"
    sup._pyrnnoise = MagicMock()
    sup.available = True
    sup.close()
    assert sup._pyrnnoise is None
    assert sup.available is False


def test_close_idempotent():
    sup = RNNoiseSuppressor(enabled=False)
    sup.close()
    sup.close()  # should not raise


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------

def test_process_disabled():
    sup = RNNoiseSuppressor(enabled=False)
    audio = np.ones(100, dtype=np.float32)
    result = sup.process(audio, 48000)
    assert result.applied is False
    np.testing.assert_array_equal(result.audio, audio)


def test_process_wrong_sample_rate():
    sup = RNNoiseSuppressor(enabled=False)
    sup.enabled = True
    sup.available = True
    sup._lib = MagicMock()
    sup._state = ctypes.c_void_p(1)
    sup._backend = "ctypes"
    result = sup.process(np.ones(100, dtype=np.float32), 16000)
    assert result.applied is False
    assert result.available is True


def test_process_empty_audio():
    sup = RNNoiseSuppressor(enabled=False)
    sup.enabled = True
    sup.available = True
    sup._lib = MagicMock()
    sup._state = ctypes.c_void_p(1)
    sup._backend = "ctypes"
    result = sup.process(np.empty(0, dtype=np.float32), 48000)
    assert result.applied is False


def test_process_ctypes_path():
    sup = RNNoiseSuppressor(enabled=False)
    sup.enabled = True
    sup.available = True
    sup._backend = "ctypes"
    sup._lib = MagicMock()
    sup._state = ctypes.c_void_p(1)
    rng = np.random.default_rng(0)
    audio = rng.standard_normal(FRAME_SIZE * 2).astype(np.float32)
    result = sup.process(audio, 48000)
    assert result.applied is True
    assert result.audio.shape[0] == audio.shape[0]
    assert sup._lib.rnnoise_process_frame.call_count == 2


def test_process_pyrnnoise_dispatch():
    sup = RNNoiseSuppressor(enabled=False)
    sup.enabled = True
    sup.available = True
    sup._backend = "pyrnnoise"
    sup._pyrnnoise = MagicMock()
    # Mock denoise_chunk to return some data
    denoised = np.zeros((1, 480), dtype=np.int16)
    sup._pyrnnoise.denoise_chunk.return_value = [(0, denoised)]
    audio = np.ones(480, dtype=np.float32)
    result = sup.process(audio, 48000)
    assert result.applied is True


# ---------------------------------------------------------------------------
# _process_pyrnnoise
# ---------------------------------------------------------------------------

def test_process_pyrnnoise_none():
    sup = RNNoiseSuppressor(enabled=False)
    sup._pyrnnoise = None
    audio = np.ones(100, dtype=np.float32)
    result = sup._process_pyrnnoise(audio)
    assert result.applied is False
    assert result.available is False


def test_process_pyrnnoise_empty_frames():
    sup = RNNoiseSuppressor(enabled=False)
    sup._pyrnnoise = MagicMock()
    sup._pyrnnoise.denoise_chunk.return_value = []
    audio = np.ones(480, dtype=np.float32)
    result = sup._process_pyrnnoise(audio)
    assert result.applied is False
    assert result.available is True


# ---------------------------------------------------------------------------
# _resolve_rnnoise_library_path
# ---------------------------------------------------------------------------

def test_resolve_rnnoise_library_path_env_var(tmp_path: Path, monkeypatch):
    lib = tmp_path / "librnnoise.dylib"
    lib.write_bytes(b"fake")
    monkeypatch.setenv("RNNOISE_LIB", str(lib))
    assert _resolve_rnnoise_library_path() == str(lib)


def test_resolve_rnnoise_library_path_find_library(monkeypatch):
    monkeypatch.delenv("RNNOISE_LIB", raising=False)
    with patch("murmur.noise.ctypes.util.find_library", return_value="librnnoise.so"):
        assert _resolve_rnnoise_library_path() == "librnnoise.so"


def test_resolve_rnnoise_library_path_candidate(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("RNNOISE_LIB", raising=False)
    candidate = tmp_path / "rnnoise"
    candidate.write_bytes(b"fake")
    with patch("murmur.noise.ctypes.util.find_library", return_value=None), \
         patch("murmur.noise._candidate_rnnoise_paths", return_value=[candidate]):
        assert _resolve_rnnoise_library_path() == str(candidate)


def test_resolve_rnnoise_library_path_none(monkeypatch):
    monkeypatch.delenv("RNNOISE_LIB", raising=False)
    with patch("murmur.noise.ctypes.util.find_library", return_value=None), \
         patch("murmur.noise._candidate_rnnoise_paths", return_value=[]):
        assert _resolve_rnnoise_library_path() is None


# ---------------------------------------------------------------------------
# _candidate_rnnoise_paths with caskroom dirs
# ---------------------------------------------------------------------------

def test_candidate_rnnoise_paths_caskroom(tmp_path: Path, monkeypatch):
    cask_root = tmp_path / "Caskroom" / "rnnoise"
    v1 = cask_root / "1.0"
    v2 = cask_root / "2.0"
    v1.mkdir(parents=True)
    v2.mkdir(parents=True)

    _HOMEBREW_CASK = "/opt/homebrew/Caskroom/rnnoise"

    original_exists = Path.exists
    original_iterdir = Path.iterdir

    def patched_exists(path: Path) -> bool:
        if str(path) == _HOMEBREW_CASK:
            return True
        if str(path) == "/usr/local/Caskroom/rnnoise":
            return False
        return original_exists(path)

    def patched_iterdir(path: Path):
        if str(path) == _HOMEBREW_CASK:
            return iter([v1, v2])
        return original_iterdir(path)

    monkeypatch.setattr(Path, "exists", patched_exists)
    monkeypatch.setattr(Path, "iterdir", patched_iterdir)

    paths = _candidate_rnnoise_paths()
    # Should have 2 base + caskroom entries
    assert len(paths) >= 4
    expected_v2 = v2 / "macos-rnnoise/rnnoise.component/Contents/MacOS/rnnoise"
    expected_v1 = v1 / "macos-rnnoise/rnnoise.component/Contents/MacOS/rnnoise"
    assert expected_v2 in paths
    assert expected_v1 in paths
    # v2.0 should come before v1.0 (reverse sorted)
    assert paths.index(expected_v2) < paths.index(expected_v1)
