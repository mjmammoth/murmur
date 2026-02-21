from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Literal

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
    task: asyncio.Task | None = None

    def snapshot(self) -> DownloadTaskSnapshot:
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
        task: asyncio.Task | None = None,
    ) -> threading.Event:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, key: str) -> CancelResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_all(self) -> list[CancelResult]:
        raise NotImplementedError

    @abstractmethod
    def resolve_single_candidate(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def snapshot(self) -> list[DownloadTaskSnapshot]:
        raise NotImplementedError


class SerialModelTaskQueue(ModelTaskQueue):
    """
    Track model download queue state in a single global serial queue.

    Bridge execution is responsible for serializing work. This class tracks
    state, cancellation events, and candidate resolution for cancel requests.
    """

    def __init__(self, history_limit: int = 128) -> None:
        self._lock = threading.RLock()
        self._entries: "OrderedDict[str, _DownloadTaskEntry]" = OrderedDict()
        self._history_limit = max(16, history_limit)

    def enqueue_download(
        self,
        key: str,
        model: str,
        runtime: str,
        task: asyncio.Task | None = None,
    ) -> threading.Event:
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

    def bind_task(self, key: str, task: asyncio.Task) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.task = task

    def cancel_event_for(self, key: str) -> threading.Event | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            return entry.cancel_event

    def mark_running(self, key: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if entry.state == "queued":
                entry.state = "running"

    def mark_completed(self, key: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.state = "completed"
            self._prune_history()

    def mark_failed(self, key: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.state = "failed"
            self._prune_history()

    def mark_cancelled(self, key: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.state = "cancelled"
            entry.cancel_event.set()
            self._prune_history()

    def cancel(self, key: str) -> CancelResult:
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

            return CancelResult(status="not_found", task=entry.snapshot())

    def cancel_all(self) -> list[CancelResult]:
        results: list[CancelResult] = []
        for key in self.pending_keys():
            results.append(self.cancel(key))
        return results

    def resolve_single_candidate(self) -> str | None:
        with self._lock:
            pending = self.pending_keys()
            if len(pending) != 1:
                return None
            return pending[0]

    def snapshot(self) -> list[DownloadTaskSnapshot]:
        with self._lock:
            return [entry.snapshot() for entry in self._entries.values()]

    def pending_keys(self) -> list[str]:
        with self._lock:
            return [
                entry.key
                for entry in self._entries.values()
                if entry.state in _PENDING_STATES
            ]

    def has_pending(self) -> bool:
        with self._lock:
            return any(entry.state in _PENDING_STATES for entry in self._entries.values())

    def keys_matching(self, model: str, runtime: str | None = None) -> list[str]:
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
