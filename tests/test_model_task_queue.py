from __future__ import annotations

from unittest.mock import Mock

from whisper_local.model_task_queue import SerialModelTaskQueue


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
    queue.enqueue_download("whisper.cpp:base", model="base", runtime="whisper.cpp")
    queue.mark_running("whisper.cpp:base")

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
    queue.enqueue_download(key, model="small", runtime="faster-whisper")
    queue.mark_completed(key)

    result = queue.cancel(key)

    assert result.status == "already_completed"
    assert result.task is not None
    assert result.task.state == "completed"


def test_queue_cancel_failed_task_reports_terminal_status():
    queue = SerialModelTaskQueue()
    key = "faster-whisper:small"
    queue.enqueue_download(key, model="small", runtime="faster-whisper")
    queue.mark_failed(key)

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
