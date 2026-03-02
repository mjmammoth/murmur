from __future__ import annotations

import argparse
import asyncio
import atexit
import json
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

import objc
import websockets
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSColor,
    NSForegroundColorAttributeName,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSMutableAttributedString, NSObject
from PyObjCTools import AppHelper
from murmur.service_state import ensure_state_directory

try:
    import fcntl
except ImportError:  # pragma: no cover - non-posix fallback
    fcntl = None  # type: ignore[assignment]

_F = TypeVar("_F", bound=Callable[..., object])
python_method = cast(Callable[[_F], _F], objc.python_method)
StatusCallback = Callable[[str, str], None]


class _SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any | None = None
        self._acquired = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle
        self._acquired = True
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if fcntl is not None:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()
        finally:
            self._handle = None
            self._acquired = False


def _status_indicator_lock() -> _SingleInstanceLock:
    state_dir = ensure_state_directory()
    return _SingleInstanceLock(state_dir / "status-indicator.lock")


class StatusListenerThread(threading.Thread):
    def __init__(self, host: str, port: int, on_status: StatusCallback) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.on_status = on_status
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        asyncio.run(self._run())

    def _dispatch_status_message(self, raw: str | bytes) -> None:
        """Parse a raw WebSocket message and dispatch status updates to the callback."""
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        if message.get("type") != "status":
            return
        status = str(message.get("status", "ready"))
        detail = str(message.get("message", "Ready"))
        AppHelper.callAfter(self.on_status, status, detail)

    async def _listen_on_socket(self, socket: Any) -> None:
        """Read status messages from a connected WebSocket until stopped."""
        AppHelper.callAfter(self.on_status, "ready", "Connected")
        async for raw in socket:
            if self._stop_event.is_set():
                return
            self._dispatch_status_message(raw)

    async def _run(self) -> None:
        url = f"ws://{self.host}:{self.port}?client=status-indicator"
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as socket:
                    await self._listen_on_socket(socket)
            except Exception:
                if self._stop_event.is_set():
                    return
                AppHelper.callAfter(self.on_status, "connecting", "Waiting for backend")
                await asyncio.sleep(1.0)


class MenuBarStatusApp(NSObject):  # type: ignore[misc]
    def initWithHost_port_(self, host: str, port: int) -> MenuBarStatusApp | None:
        self = objc.super(MenuBarStatusApp, self).init()
        if self is None:
            return None

        self._bridge_status = "connecting"
        self._bridge_message = "Waiting for backend"
        self._success_timer: threading.Timer | None = None
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self._button = self._status_item.button()
        self._listener = StatusListenerThread(host, port, self.updateBridgeStatus_message_)

        menu = NSMenu.alloc().init()
        title_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "murmur",
            None,
            "",
        )
        title_item.setEnabled_(False)
        menu.addItem_(title_item)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Status Indicator",
            "quitIndicator:",
            "q",
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self._status_item.setMenu_(menu)

        self._set_visual("idle", self._bridge_message)
        return self

    @python_method
    def start(self) -> None:
        self._listener.start()

    @python_method
    def stop(self) -> None:
        self._cancel_success_timer()
        self._listener.stop()

    def quitIndicator_(self, _sender: Any) -> None:
        self.stop()
        AppHelper.stopEventLoop()

    def updateBridgeStatus_message_(self, status: str, message: str) -> None:
        previous_status = self._bridge_status
        self._bridge_status = status
        self._bridge_message = message

        if status == "ready" and previous_status == "transcribing" and message == "Ready":
            self._set_visual("success", "Transcription complete")
            self._schedule_success_reset()
            return

        self._cancel_success_timer()
        self._set_visual(status, message)

    @python_method
    def _schedule_success_reset(self) -> None:
        self._cancel_success_timer()
        timer = threading.Timer(2.0, lambda: AppHelper.callAfter(self._reset_to_idle_if_ready))
        timer.daemon = True
        self._success_timer = timer
        timer.start()

    @python_method
    def _cancel_success_timer(self) -> None:
        if self._success_timer is None:
            return
        self._success_timer.cancel()
        self._success_timer = None

    def _reset_to_idle_if_ready(self) -> None:
        self._success_timer = None
        if self._bridge_status == "ready":
            self._set_visual("idle", self._bridge_message)

    @python_method
    def _set_visual(self, status: str, message: str) -> None:
        if status == "recording":
            color = NSColor.systemRedColor()
        elif status in {"transcribing", "downloading"}:
            color = NSColor.systemYellowColor()
        elif status == "success":
            color = NSColor.systemGreenColor()
        else:
            color = NSColor.systemGrayColor()

        title = NSMutableAttributedString.alloc().initWithString_("●")
        title.addAttribute_value_range_(NSForegroundColorAttributeName, color, (0, 1))
        self._button.setAttributedTitle_(title)
        self._button.setToolTip_(f"murmur: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m murmur.status_indicator",
        description="murmur macOS menu bar status indicator",
    )
    parser.add_argument("--host", default="localhost", help="Bridge host")
    parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    return parser


def main() -> None:
    if sys.platform != "darwin":
        return

    singleton_lock = _status_indicator_lock()
    if not singleton_lock.acquire():
        return
    atexit.register(singleton_lock.release)

    args = build_parser().parse_args()

    NSApplication.sharedApplication()
    NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    app = MenuBarStatusApp.alloc().initWithHost_port_(args.host, args.port)
    if app is None:
        return
    app.start()

    signal.signal(signal.SIGTERM, lambda *_: AppHelper.callAfter(app.quitIndicator_, None))
    signal.signal(signal.SIGINT, lambda *_: AppHelper.callAfter(app.quitIndicator_, None))

    try:
        AppHelper.runEventLoop()
    finally:
        singleton_lock.release()


if __name__ == "__main__":
    main()
