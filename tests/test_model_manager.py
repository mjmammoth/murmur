from __future__ import annotations

import os
from pathlib import Path

from whisper_local import model_manager


def _write_complete_snapshot(snapshot_path: Path, vocabulary_file: str = "vocabulary.json") -> None:
    snapshot_path.mkdir(parents=True, exist_ok=True)
    (snapshot_path / "model.bin").write_bytes(b"00")
    (snapshot_path / "config.json").write_text("{}", encoding="utf-8")
    (snapshot_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (snapshot_path / vocabulary_file).write_text("{}", encoding="utf-8")


def test_get_installed_model_path_ignores_incomplete_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    incomplete_snapshot = model_manager._model_cache_path("small") / "snapshots" / "incomplete"
    incomplete_snapshot.mkdir(parents=True, exist_ok=True)
    (incomplete_snapshot / "config.json").write_text("{}", encoding="utf-8")

    assert model_manager.get_installed_model_path("small") is None


def test_prune_invalid_model_cache_keeps_valid_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    snapshots_dir = model_manager._model_cache_path("small") / "snapshots"
    valid_snapshot = snapshots_dir / "valid"
    incomplete_snapshot = snapshots_dir / "incomplete"

    _write_complete_snapshot(valid_snapshot)
    incomplete_snapshot.mkdir(parents=True, exist_ok=True)
    (incomplete_snapshot / "config.json").write_text("{}", encoding="utf-8")

    os.utime(valid_snapshot, (100, 100))
    os.utime(incomplete_snapshot, (200, 200))

    assert model_manager.get_installed_model_path("small") == valid_snapshot

    model_manager.prune_invalid_model_cache("small")

    assert valid_snapshot.exists()
    assert not incomplete_snapshot.exists()


def test_get_installed_model_path_accepts_vocabulary_txt(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    valid_snapshot = model_manager._model_cache_path("base") / "snapshots" / "valid"
    _write_complete_snapshot(valid_snapshot, vocabulary_file="vocabulary.txt")

    assert model_manager.get_installed_model_path("base") == valid_snapshot


def test_remove_model_removes_primary_and_alias_cache_paths(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    for cache_path in model_manager._model_cache_paths("large-v3-turbo"):
        snapshot_path = cache_path / "snapshots" / "partial"
        snapshot_path.mkdir(parents=True, exist_ok=True)
        (snapshot_path / "config.json").write_text("{}", encoding="utf-8")

    model_manager.remove_model("large-v3-turbo")

    assert all(not cache_path.exists() for cache_path in model_manager._model_cache_paths("large-v3-turbo"))
