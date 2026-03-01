from __future__ import annotations

from unittest.mock import Mock

import pytest

from murmur.model_task_queue import SerialModelTaskQueue


def test_queue_cancel_queued_task_marks_cancelled_and_calls_task_cancel():
    queue = SerialModelTaskQueue()
    task = Mock()
    task.done.return_value = False
    queue.enqueue_download("faster-whisper:small", model="small", runtime="faster-whisper", task=task)

    result = queue.cancel("faster-whisper:small")

    assert result.status == "queued"
    assert result.task is not None
    assert result.task.state == "cancelled"
    task.cancel.assert_called_once()


def test_queue_cancel_running_task_sets_active_status():
    queue = SerialModelTaskQueue()
    queue_task = Mock()
    queue_task.done.return_value = False
    queue.enqueue_download(
        "whisper.cpp:base", model="base", runtime="whisper.cpp", task=queue_task
    )
    queue.mark_running("whisper.cpp:base", task=queue_task)

    result = queue.cancel("whisper.cpp:base")

    assert result.status == "active"
    event = queue.cancel_event_for("whisper.cpp:base")
    assert event is not None and event.is_set()


def test_queue_resolve_single_candidate_only_when_one_pending():
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    assert queue.resolve_single_candidate() == "faster-whisper:tiny"

    queue.enqueue_download("whisper.cpp:small", model="small", runtime="whisper.cpp")
    assert queue.resolve_single_candidate() is None


def test_queue_cancel_completed_task_reports_terminal_status():
    queue = SerialModelTaskQueue()
    key = "faster-whisper:small"
    queue_task = Mock()
    queue_task.done.return_value = False
    queue.enqueue_download(key, model="small", runtime="faster-whisper", task=queue_task)
    queue.mark_completed(key, task=queue_task)

    result = queue.cancel(key)

    assert result.status == "already_completed"
    assert result.task is not None
    assert result.task.state == "completed"


def test_queue_cancel_failed_task_reports_terminal_status():
    queue = SerialModelTaskQueue()
    key = "faster-whisper:small"
    queue_task = Mock()
    queue_task.done.return_value = False
    queue.enqueue_download(key, model="small", runtime="faster-whisper", task=queue_task)
    queue.mark_failed(key, task=queue_task)

    result = queue.cancel(key)

    assert result.status == "already_failed"
    assert result.task is not None
    assert result.task.state == "failed"


def test_queue_ignores_stale_task_mark_callbacks_after_reenqueue():
    queue = SerialModelTaskQueue()
    key = "faster-whisper:small"

    stale_task = Mock()
    stale_task.done.return_value = False
    current_task = Mock()
    current_task.done.return_value = False

    queue.enqueue_download(key, model="small", runtime="faster-whisper", task=stale_task)
    queue.enqueue_download(key, model="small", runtime="faster-whisper", task=current_task)

    queue.mark_completed(key, task=stale_task)
    stale_snapshot = next(entry for entry in queue.snapshot() if entry.key == key)
    assert stale_snapshot.state == "queued"

    queue.mark_completed(key, task=current_task)
    current_snapshot = next(entry for entry in queue.snapshot() if entry.key == key)
    assert current_snapshot.state == "completed"


def test_queue_bind_task_associates_task_with_entry():
    """Test bind_task associates an asyncio task with a queue entry."""
    queue = SerialModelTaskQueue()
    task = Mock()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")

    queue.bind_task("faster-whisper:tiny", task)

    # Verify by checking the task is used in mark_completed
    queue.mark_completed("faster-whisper:tiny", task=task)
    snapshot = next(entry for entry in queue.snapshot() if entry.key == "faster-whisper:tiny")
    assert snapshot.state == "completed"


def test_queue_bind_task_ignores_nonexistent_key():
    """Test bind_task does nothing for nonexistent key."""
    queue = SerialModelTaskQueue()
    task = Mock()

    # Should not raise
    queue.bind_task("nonexistent", task)


def test_queue_bind_task_ignores_different_task():
    """Test bind_task ignores bind attempt with different task."""
    queue = SerialModelTaskQueue()
    task1 = Mock()
    task2 = Mock()

    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper", task=task1)
    queue.bind_task("faster-whisper:tiny", task2)

    # Original task should still be used
    queue.mark_completed("faster-whisper:tiny", task=task1)
    snapshot = next(entry for entry in queue.snapshot() if entry.key == "faster-whisper:tiny")
    assert snapshot.state == "completed"


def test_queue_cancel_event_for_returns_event():
    """Test cancel_event_for returns the cancel event for a key."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")

    event = queue.cancel_event_for("faster-whisper:tiny")

    assert event is not None
    assert not event.is_set()


def test_queue_cancel_event_for_nonexistent_key():
    """Test cancel_event_for returns None for nonexistent key."""
    queue = SerialModelTaskQueue()

    event = queue.cancel_event_for("nonexistent")

    assert event is None


def test_queue_mark_running_transitions_from_queued():
    """Test mark_running transitions state from queued to running."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")

    queue.mark_running("faster-whisper:tiny")

    snapshot = next(entry for entry in queue.snapshot() if entry.key == "faster-whisper:tiny")
    assert snapshot.state == "running"


def test_queue_mark_running_ignores_nonqueued_state():
    """Test mark_running does not change non-queued states."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.mark_running("faster-whisper:tiny")
    queue.mark_completed("faster-whisper:tiny")

    # Try to mark running again - should be ignored
    queue.mark_running("faster-whisper:tiny")

    snapshot = next(entry for entry in queue.snapshot() if entry.key == "faster-whisper:tiny")
    assert snapshot.state == "completed"


def test_queue_mark_cancelled_sets_state_and_event():
    """Test mark_cancelled sets cancelled state and cancel event."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")

    queue.mark_cancelled("faster-whisper:tiny")

    snapshot = next(entry for entry in queue.snapshot() if entry.key == "faster-whisper:tiny")
    assert snapshot.state == "cancelled"

    event = queue.cancel_event_for("faster-whisper:tiny")
    assert event.is_set()


def test_queue_mark_cancelled_ignores_mismatched_task():
    """Test mark_cancelled ignores task identity mismatch."""
    queue = SerialModelTaskQueue()
    task1 = Mock()
    task2 = Mock()

    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper", task=task1)

    queue.mark_cancelled("faster-whisper:tiny", task=task2)

    snapshot = next(entry for entry in queue.snapshot() if entry.key == "faster-whisper:tiny")
    assert snapshot.state == "queued"  # Should not be cancelled


def test_queue_cancel_not_found():
    """Test cancel returns not_found status for nonexistent key."""
    queue = SerialModelTaskQueue()

    result = queue.cancel("nonexistent")

    assert result.status == "not_found"
    assert result.task is None


def test_queue_cancel_already_cancelling():
    """Test cancel returns already_cancelling for task in cancelling state."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.mark_running("faster-whisper:tiny")
    queue.cancel("faster-whisper:tiny")  # First cancel -> cancelling

    result = queue.cancel("faster-whisper:tiny")  # Second cancel

    assert result.status == "already_cancelling"


def test_queue_cancel_already_cancelled():
    """Test cancel returns already_cancelled for cancelled task."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.mark_cancelled("faster-whisper:tiny")

    result = queue.cancel("faster-whisper:tiny")

    assert result.status == "already_cancelled"


def test_queue_cancel_all_cancels_pending_tasks():
    """Test cancel_all cancels all pending tasks."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.enqueue_download("faster-whisper:small", model="small", runtime="faster-whisper")
    queue.enqueue_download("faster-whisper:base", model="base", runtime="faster-whisper")
    queue.mark_completed("faster-whisper:base")  # One completed

    results = queue.cancel_all()

    assert len(results) == 2  # Only pending tasks
    assert all(r.status in ("queued", "active") for r in results)


def test_queue_pending_keys_returns_pending_only():
    """Test pending_keys returns only tasks in pending states."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.enqueue_download("faster-whisper:small", model="small", runtime="faster-whisper")
    queue.mark_running("faster-whisper:small")
    queue.enqueue_download("faster-whisper:base", model="base", runtime="faster-whisper")
    queue.mark_completed("faster-whisper:base")

    keys = queue.pending_keys()

    assert "faster-whisper:tiny" in keys
    assert "faster-whisper:small" in keys
    assert "faster-whisper:base" not in keys


def test_queue_has_pending_true():
    """Test has_pending returns True when pending tasks exist."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")

    assert queue.has_pending() is True


def test_queue_has_pending_false():
    """Test has_pending returns False when no pending tasks."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.mark_completed("faster-whisper:tiny")

    assert queue.has_pending() is False


def test_queue_keys_matching_filters_by_model():
    """Test keys_matching filters by model name."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.enqueue_download("faster-whisper:small", model="small", runtime="faster-whisper")
    queue.enqueue_download("whisper.cpp:tiny", model="tiny", runtime="whisper.cpp")

    keys = queue.keys_matching("tiny")

    assert len(keys) == 2
    assert "faster-whisper:tiny" in keys
    assert "whisper.cpp:tiny" in keys


def test_queue_keys_matching_filters_by_runtime():
    """Test keys_matching filters by runtime when specified."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.enqueue_download("whisper.cpp:tiny", model="tiny", runtime="whisper.cpp")

    keys = queue.keys_matching("tiny", runtime="faster-whisper")

    assert len(keys) == 1
    assert "faster-whisper:tiny" in keys


def test_queue_keys_matching_excludes_completed():
    """Test keys_matching excludes non-pending tasks."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.mark_completed("faster-whisper:tiny")
    queue.enqueue_download("whisper.cpp:tiny", model="tiny", runtime="whisper.cpp")

    keys = queue.keys_matching("tiny")

    assert len(keys) == 1
    assert "whisper.cpp:tiny" in keys


def test_queue_snapshot_returns_all_entries():
    """Test snapshot returns all queue entries."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.enqueue_download("faster-whisper:small", model="small", runtime="faster-whisper")

    snapshot = queue.snapshot()

    assert len(snapshot) == 2
    assert all(hasattr(entry, "key") for entry in snapshot)
    assert all(hasattr(entry, "state") for entry in snapshot)


def test_queue_snapshot_includes_completed():
    """Test snapshot includes completed tasks."""
    queue = SerialModelTaskQueue()
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.mark_completed("faster-whisper:tiny")

    snapshot = queue.snapshot()

    assert len(snapshot) == 1
    assert snapshot[0].state == "completed"


def test_queue_prune_history_limits_entries():
    """Test _prune_history removes old completed entries."""
    # Use larger limit to exceed minimum of 16
    queue = SerialModelTaskQueue(history_limit=20)

    # Add more entries than the limit
    for i in range(25):
        key = f"faster-whisper:model{i}"
        queue.enqueue_download(key, model=f"model{i}", runtime="faster-whisper")
        queue.mark_completed(key)

    snapshot = queue.snapshot()
    assert len(snapshot) <= 20


def test_queue_prune_history_keeps_pending():
    """Test _prune_history keeps pending tasks regardless of limit."""
    queue = SerialModelTaskQueue(history_limit=2)

    # Add 3 pending tasks
    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper")
    queue.enqueue_download("faster-whisper:small", model="small", runtime="faster-whisper")
    queue.enqueue_download("faster-whisper:base", model="base", runtime="faster-whisper")

    snapshot = queue.snapshot()
    assert len(snapshot) == 3  # All kept because pending


def test_queue_enqueue_cancels_existing_pending():
    """Test enqueue_download cancels existing pending task with same key."""
    queue = SerialModelTaskQueue()
    task1 = Mock()
    task1.done.return_value = False
    task2 = Mock()

    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper", task=task1)
    event1 = queue.cancel_event_for("faster-whisper:tiny")

    queue.enqueue_download("faster-whisper:tiny", model="tiny", runtime="faster-whisper", task=task2)

    assert event1.is_set()
    task1.cancel.assert_called_once()


def test_queue_min_history_limit():
    """Test SerialModelTaskQueue enforces minimum history limit."""
    queue = SerialModelTaskQueue(history_limit=1)

    # Should enforce minimum of 16
    for i in range(20):
        key = f"faster-whisper:model{i}"
        queue.enqueue_download(key, model=f"model{i}", runtime="faster-whisper")
        queue.mark_completed(key)

    snapshot = queue.snapshot()
    assert len(snapshot) >= 16


def test_queue_task_state_transitions():
    """Test full task state transition lifecycle."""
    queue = SerialModelTaskQueue()
    key = "faster-whisper:tiny"

    # queued -> running -> cancelling -> cancelled
    queue.enqueue_download(key, model="tiny", runtime="faster-whisper")
    assert queue.snapshot()[0].state == "queued"

    queue.mark_running(key)
    assert queue.snapshot()[0].state == "running"

    queue.cancel(key)
    assert queue.snapshot()[0].state == "cancelling"

    queue.mark_cancelled(key)
    assert queue.snapshot()[0].state == "cancelled"


def test_queue_concurrent_safety():
    """Test queue operations are thread-safe."""
    import threading

    queue = SerialModelTaskQueue()
    errors = []

    def worker(i):
        try:
            key = f"faster-whisper:model{i}"
            queue.enqueue_download(key, model=f"model{i}", runtime="faster-whisper")
            queue.mark_running(key)
            queue.mark_completed(key)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(queue.snapshot()) == 10


def test_download_task_snapshot_immutability():
    """Test DownloadTaskSnapshot is immutable."""
    from murmur.model_task_queue import DownloadTaskSnapshot

    snapshot = DownloadTaskSnapshot(
        key="test",
        model="tiny",
        runtime="faster-whisper",
        state="queued",
    )

    # Should not be able to modify
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        snapshot.state = "running"


def test_cancel_result_immutability():
    """Test CancelResult is immutable."""
    from murmur.model_task_queue import CancelResult, DownloadTaskSnapshot

    task_snapshot = DownloadTaskSnapshot(
        key="test",
        model="tiny",
        runtime="faster-whisper",
        state="queued",
    )
    result = CancelResult(status="queued", task=task_snapshot)

    # Should not be able to modify
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        result.status = "cancelled"
