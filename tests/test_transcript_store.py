from __future__ import annotations

from pathlib import Path

from whisper_local.transcript_store import TranscriptStore


def test_append_and_history_round_trip(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "transcripts.sqlite3", max_entries=10)

    first = store.append("hello world", timestamp="12:00:00")
    history = store.history()

    assert len(history) == 1
    assert history[0].id == first.id
    assert history[0].text == "hello world"
    assert history[0].timestamp == "12:00:00"
    assert isinstance(history[0].created_at, str)


def test_history_limit_returns_latest_entries(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "transcripts.sqlite3", max_entries=10)
    store.append("a", timestamp="12:00:00")
    store.append("b", timestamp="12:00:01")
    store.append("c", timestamp="12:00:02")

    history = store.history(limit=2)

    assert [entry.text for entry in history] == ["b", "c"]


def test_append_prunes_to_max_entries(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "transcripts.sqlite3", max_entries=3)

    store.append("one", timestamp="12:00:00")
    store.append("two", timestamp="12:00:01")
    store.append("three", timestamp="12:00:02")
    store.append("four", timestamp="12:00:03")

    history = store.history()

    assert len(history) == 3
    assert [entry.text for entry in history] == ["two", "three", "four"]
