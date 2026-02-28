from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Literal

TaskState = Literal[
    "queued",
    "running",
    "cancelling",
    "completed",
    "cancelled",
    "failed",
]
CancelStatus = Literal[
    "active",
    "queued",
    "already_cancelling",
    "already_cancelled",
    "already_completed",
    "already_failed",
    "not_found",
]
_PENDING_STATES: set[TaskState] = {"queued", "running", "cancelling"}


@dataclass(frozen=True)
class DownloadTaskSnapshot:
    key: str
    model: str
    runtime: str
    state: TaskState


@dataclass
class _DownloadTaskEntry:
    key: str
    model: str
    runtime: str
    state: TaskState = "queued"
    cancel_event: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task[Any] | None = None

    def snapshot(self) -> DownloadTaskSnapshot:
        """
        Create an immutable snapshot of this entry's identity and current state.

        Returns:
            DownloadTaskSnapshot: Snapshot containing the entry's `key`, `model`, `runtime`, and `state`.
        """
        return DownloadTaskSnapshot(
            key=self.key,
            model=self.model,
            runtime=self.runtime,
            state=self.state,
        )


@dataclass(frozen=True)
class CancelResult:
    status: CancelStatus
    task: DownloadTaskSnapshot | None


class ModelTaskQueue(ABC):
    @abstractmethod
    def enqueue_download(
        self,
        key: str,
        model: str,
        runtime: str,
        task: asyncio.Task[Any] | None = None,
    ) -> threading.Event:
        """
        Enqueue a model download task and return a cancellation event for that task.

        Parameters:
            key (str): Unique identifier for the download task.
            model (str): Model name or identifier to download.
            runtime (str): Target runtime/environment for the download.
            task (asyncio.Task[Any] | None): Optional asyncio.Task associated with this download; may be bound to the queue entry.

        Returns:
            threading.Event: An event that will be set to signal that the enqueued task has been cancelled.
        """
        raise NotImplementedError

    @abstractmethod
    def cancel(self, key: str) -> CancelResult:
        """
        Cancel the tracked download task identified by `key`.

        Parameters:
            key (str): The unique key of the task to cancel.

        Returns:
            CancelResult: An object with `status` indicating the cancellation outcome and `task` containing a DownloadTaskSnapshot for the affected task when available (otherwise `None`).
        """
        raise NotImplementedError

    @abstractmethod
    def cancel_all(self) -> list[CancelResult]:
        """
        Cancel all pending download tasks and return their cancellation results.

        Returns:
            list[CancelResult]: A list of CancelResult objects describing the outcome for each task that was pending at the time of cancellation.
        """
        raise NotImplementedError

    @abstractmethod
    def resolve_single_candidate(self) -> str | None:
        """
        Get the key of the sole pending download candidate, if exactly one exists.

        Returns:
            key (str | None): The key of the single pending candidate, or `None` when there are zero or multiple pending candidates.
        """
        raise NotImplementedError

    @abstractmethod
    def snapshot(self) -> list[DownloadTaskSnapshot]:
        """
        Return snapshots of all tracked download tasks.

        Each snapshot is an immutable view of a task's key, model, runtime, and current state.

        Returns:
            list[DownloadTaskSnapshot]: A list of snapshots representing the current state of every tracked download task.
        """
        raise NotImplementedError


class SerialModelTaskQueue(ModelTaskQueue):
    """
    Track model download queue state in a single global serial queue.

    Bridge execution is responsible for serializing work. This class tracks
    state, cancellation events, and candidate resolution for cancel requests.
    """

    def __init__(self, history_limit: int = 128) -> None:
        """
        Initialize the serial model task queue.

        Parameters:
        	history_limit (int): Maximum number of task entries to retain in history; values less than 16 are raised to 16.

        Description:
        	Creates the reentrant lock, the ordered mapping of task entries, and stores the effective history limit.
        """
        self._lock = threading.RLock()
        self._entries: "OrderedDict[str, _DownloadTaskEntry]" = OrderedDict()
        self._history_limit = max(16, history_limit)

    def enqueue_download(
        self,
        key: str,
        model: str,
        runtime: str,
        task: asyncio.Task[Any] | None = None,
    ) -> threading.Event:
        """
        Enqueue a download task for the given key, replacing any existing pending entry for that key.

        If a pending entry with the same key exists, its cancellation event will be signaled and its associated asyncio Task will be requested to cancel. The provided optional `task` will be associated with the new entry.

        Parameters:
            key: Identifier for the download task.
            model: Model name or identifier to download.
            runtime: Runtime identifier associated with the download.
            task: Optional asyncio.Task[Any] representing the running download to bind to the new entry.

        Returns:
            threading.Event: An event that will be set when the enqueued task is cancelled.
        """
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None and existing.state in _PENDING_STATES:
                existing.cancel_event.set()
                if existing.task is not None and not existing.task.done():
                    existing.task.cancel()
            entry = _DownloadTaskEntry(key=key, model=model, runtime=runtime, task=task)
            self._entries[key] = entry
            self._prune_history()
            return entry.cancel_event

    def bind_task(self, key: str, task: asyncio.Task[Any]) -> None:
        """
        Associate an asyncio Task with the download entry identified by `key` when appropriate.

        Binds `task` to the existing entry if the entry exists and either has no task bound or is already bound to the same task. If no entry exists or the entry is already bound to a different task, the call is a no-op.

        Parameters:
            key (str): Identifier of the download entry to bind the task to.
            task (asyncio.Task[Any]): The asyncio Task to associate with the entry.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if entry.task is not None and entry.task is not task:
                return
            entry.task = task

    def cancel_event_for(self, key: str) -> threading.Event | None:
        """
        Return the cancel event associated with a tracked download task key, if any.

        Parameters:
            key (str): The task key to look up.

        Returns:
            threading.Event | None: The task's cancel event if the key exists, otherwise `None`.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            return entry.cancel_event

    @staticmethod
    def _task_matches(entry: _DownloadTaskEntry, task: asyncio.Task[Any] | None) -> bool:
        """
        Check whether the provided asyncio Task corresponds to the entry's bound task or is unspecified.

        Returns:
            bool: `True` if `task` is `None` or is the same object as `entry.task`, `False` otherwise.
        """
        if task is None:
            return True
        return entry.task is task

    def mark_running(self, key: str, task: asyncio.Task[Any] | None = None) -> None:
        """
        Mark the task with the given key as running if it exists and matches the provided asyncio task.

        If an entry for `key` is present and either `task` is None or matches the entry's bound task, the entry's state is changed from "queued" to "running". If the entry is missing, the task does not match, or the entry is not in the "queued" state, no change is made.

        Parameters:
            key (str): The task key to transition.
            task (asyncio.Task[Any] | None): Optional asyncio.Task used to ensure the transition applies only to the intended entry; if None, the state change is applied regardless of the entry's bound task.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if not self._task_matches(entry, task):
                return
            if entry.state == "queued":
                entry.state = "running"

    def mark_completed(self, key: str, task: asyncio.Task[Any] | None = None) -> None:
        """
        Mark the tracked entry identified by `key` as completed if it exists and matches the optional `task`.

        If an entry exists for `key` and `task` is None or matches the entry's bound asyncio.Task, the entry's state is set to "completed" and queue history may be pruned.

        Parameters:
            key (str): Identifier of the download task to mark completed.
            task (asyncio.Task[Any] | None): If provided, only mark the entry completed when its bound task is the same; if None, match is not required.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if not self._task_matches(entry, task):
                return
            entry.state = "completed"
            self._prune_history()

    def mark_failed(self, key: str, task: asyncio.Task[Any] | None = None) -> None:
        """
        Mark a tracked download task as failed.

        Sets the entry's state to "failed" if an entry with the given key exists and the optional `task` argument matches the entry's bound asyncio.Task (or if `task` is None), then prunes history.

        Parameters:
            key (str): Identifier of the tracked download task.
            task (asyncio.Task[Any] | None): Optional task to verify before updating; if provided, the entry is updated only when it refers to the same asyncio.Task.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if not self._task_matches(entry, task):
                return
            entry.state = "failed"
            self._prune_history()

    def mark_cancelled(self, key: str, task: asyncio.Task[Any] | None = None) -> None:
        """
        Mark the queued or running download identified by `key` as cancelled.

        If an entry with `key` exists and the optional `task` matches the entry's bound task (or `task` is None), this updates the entry's state to "cancelled", signals its cancellation event, and prunes history. If no matching entry is found the call is a no-op.

        Parameters:
            key (str): Identifier of the download entry to cancel.
            task (asyncio.Task[Any] | None): Optional task to match against the entry; when provided, the entry is only updated if its bound task is the same.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if not self._task_matches(entry, task):
                return
            entry.state = "cancelled"
            entry.cancel_event.set()
            self._prune_history()

    def cancel(self, key: str) -> CancelResult:
        """
        Attempt to cancel the tracked download task identified by `key`.

        Parameters:
            key (str): Unique identifier for the download task to cancel.

        Returns:
            CancelResult: Outcome of the cancel operation.
                - status == "not_found": no task with `key` is tracked.
                - status == "queued": the task was queued and is now transitioned to "cancelled"; its cancel event is set and any associated asyncio.Task is cancelled if still running. The `task` field is the snapshot of the cancelled entry.
                - status == "active": the task was running and is now transitioned to "cancelling"; its cancel event is set. The `task` field is the snapshot of the entry.
                - status == "already_cancelling": the task was already in "cancelling"; `task` is the snapshot.
                - status == "already_cancelled": the task was already "cancelled"; `task` is the snapshot.
                - status == "already_completed": the task already completed; `task` is the snapshot.
                - status == "already_failed": the task already failed; `task` is the snapshot.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return CancelResult(status="not_found", task=None)

            if entry.state == "queued":
                entry.state = "cancelled"
                entry.cancel_event.set()
                if entry.task is not None and not entry.task.done():
                    entry.task.cancel()
                return CancelResult(status="queued", task=entry.snapshot())

            if entry.state == "running":
                entry.state = "cancelling"
                entry.cancel_event.set()
                return CancelResult(status="active", task=entry.snapshot())

            if entry.state == "cancelling":
                return CancelResult(status="already_cancelling", task=entry.snapshot())

            if entry.state == "cancelled":
                return CancelResult(status="already_cancelled", task=entry.snapshot())

            if entry.state == "completed":
                return CancelResult(status="already_completed", task=entry.snapshot())

            if entry.state == "failed":
                return CancelResult(status="already_failed", task=entry.snapshot())

            return CancelResult(status="not_found", task=entry.snapshot())

    def cancel_all(self) -> list[CancelResult]:
        """
        Cancel every task that is currently pending and return the outcomes.

        Attempts to cancel each entry whose state is in the pending set and collects the resulting CancelResult for each attempted cancellation in the same order as pending_keys().

        Returns:
            results (list[CancelResult]): A list of CancelResult objects describing the cancel outcome and associated task snapshot for each pending task.
        """
        results: list[CancelResult] = []
        for key in self.pending_keys():
            results.append(self.cancel(key))
        return results

    def resolve_single_candidate(self) -> str | None:
        """
        Return the key of the single pending download candidate, if exactly one exists.

        Returns:
            The key of the pending candidate as a string, or `None` if there is not exactly one pending candidate.
        """
        with self._lock:
            pending = self.pending_keys()
            if len(pending) != 1:
                return None
            return pending[0]

    def snapshot(self) -> list[DownloadTaskSnapshot]:
        """
        Return snapshots of all tracked download tasks in insertion order.

        Returns:
            list[DownloadTaskSnapshot]: A list of immutable snapshots representing each tracked task's key, model, runtime, and current state, ordered by their insertion in the queue.
        """
        with self._lock:
            return [entry.snapshot() for entry in self._entries.values()]

    def pending_keys(self) -> list[str]:
        """
        Return the keys of all tasks that are currently pending.

        Pending tasks are those whose state is "queued", "running", or "cancelling".

        Returns:
            list[str]: List of task keys that are in a pending state, ordered by insertion.
        """
        with self._lock:
            return [
                entry.key
                for entry in self._entries.values()
                if entry.state in _PENDING_STATES
            ]

    def has_pending(self) -> bool:
        """
        Check whether any tracked download task is in a pending state.

        Pending states include "queued", "running", and "cancelling".

        Returns:
            `True` if any task is in a pending state, `False` otherwise.
        """
        with self._lock:
            return any(entry.state in _PENDING_STATES for entry in self._entries.values())

    def keys_matching(self, model: str, runtime: str | None = None) -> list[str]:
        """
        Get keys of pending download entries that match the given model and optional runtime.

        Parameters:
            model (str): Model identifier to match; leading and trailing whitespace are trimmed before comparison.
            runtime (str | None): Optional runtime string; if provided, only entries with an identical runtime are matched.

        Returns:
            list[str]: Keys of entries whose state is pending and whose model (after trimming) and runtime match the provided values.
        """
        with self._lock:
            matches: list[str] = []
            normalized_model = model.strip()
            for entry in self._entries.values():
                if entry.state not in _PENDING_STATES:
                    continue
                if entry.model != normalized_model:
                    continue
                if runtime and entry.runtime != runtime:
                    continue
                matches.append(entry.key)
            return matches

    def _prune_history(self) -> None:
        """
        Prune stored task entries to respect the configured history limit.

        Removes oldest entries whose state is not in the pending set until the total
        number of tracked entries is less than or equal to the history limit. This
        method mutates the queue's internal entries mapping.
        """
        with self._lock:
            if len(self._entries) <= self._history_limit:
                return
            removable = [
                key
                for key, entry in self._entries.items()
                if entry.state not in _PENDING_STATES
            ]
            while len(self._entries) > self._history_limit and removable:
                key = removable.pop(0)
                self._entries.pop(key, None)
