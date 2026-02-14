from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
import threading
from typing import Any

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


class StatusListenerThread(threading.Thread):
    def __init__(self, host: str, port: int, on_status) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.on_status = on_status
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        url = f"ws://{self.host}:{self.port}?client=status-indicator"
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as socket:
                    AppHelper.callAfter(self.on_status, "ready", "Connected")
                    async for raw in socket:
                        if self._stop_event.is_set():
                            return
                        try:
                            message = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if message.get("type") != "status":
                            continue
                        status = str(message.get("status", "ready"))
                        detail = str(message.get("message", "Ready"))
                        AppHelper.callAfter(self.on_status, status, detail)
            except Exception:
                if self._stop_event.is_set():
                    return
                AppHelper.callAfter(self.on_status, "connecting", "Waiting for backend")
                await asyncio.sleep(1.0)


class MenuBarStatusApp(NSObject):
    def initWithHost_port_(self, host: str, port: int):  # noqa: N802
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
            "whisper.local",
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

    @objc.python_method
    def start(self) -> None:
        self._listener.start()

    @objc.python_method
    def stop(self) -> None:
        self._cancel_success_timer()
        self._listener.stop()

    def quitIndicator_(self, _sender: Any) -> None:  # noqa: N802
        self.stop()
        AppHelper.stopEventLoop()

    def updateBridgeStatus_message_(self, status: str, message: str) -> None:  # noqa: N802
        previous_status = self._bridge_status
        self._bridge_status = status
        self._bridge_message = message

        if status == "ready" and previous_status == "transcribing" and message == "Ready":
            self._set_visual("success", "Transcription complete")
            self._schedule_success_reset()
            return

        self._cancel_success_timer()
        self._set_visual(status, message)

    @objc.python_method
    def _schedule_success_reset(self) -> None:
        self._cancel_success_timer()
        timer = threading.Timer(2.0, lambda: AppHelper.callAfter(self._reset_to_idle_if_ready))
        timer.daemon = True
        self._success_timer = timer
        timer.start()

    @objc.python_method
    def _cancel_success_timer(self) -> None:
        if self._success_timer is None:
            return
        self._success_timer.cancel()
        self._success_timer = None

    def _reset_to_idle_if_ready(self) -> None:
        self._success_timer = None
        if self._bridge_status == "ready":
            self._set_visual("idle", self._bridge_message)

    @objc.python_method
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
        self._button.setToolTip_(f"whisper.local: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m whisper_local.status_indicator",
        description="whisper.local macOS menu bar status indicator",
    )
    parser.add_argument("--host", default="localhost", help="Bridge host")
    parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    return parser


def main() -> None:
    if sys.platform != "darwin":
        return

    args = build_parser().parse_args()

    NSApplication.sharedApplication()
    NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    app = MenuBarStatusApp.alloc().initWithHost_port_(args.host, args.port)
    if app is None:
        return
    app.start()

    signal.signal(signal.SIGTERM, lambda *_: AppHelper.callAfter(app.quitIndicator_, None))
    signal.signal(signal.SIGINT, lambda *_: AppHelper.callAfter(app.quitIndicator_, None))

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
