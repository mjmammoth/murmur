from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from Quartz import (
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    CFMachPortCreateRunLoopSource,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
    kCFRunLoopCommonModes,
)


logger = logging.getLogger(__name__)


MODIFIER_FLAGS = {
    "cmd": kCGEventFlagMaskCommand,
    "command": kCGEventFlagMaskCommand,
    "ctrl": kCGEventFlagMaskControl,
    "control": kCGEventFlagMaskControl,
    "alt": kCGEventFlagMaskAlternate,
    "option": kCGEventFlagMaskAlternate,
    "shift": kCGEventFlagMaskShift,
}

KEYCODES = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "9": 25,
    "7": 26,
    "8": 28,
    "0": 29,
    "o": 31,
    "u": 32,
    "i": 34,
    "p": 35,
    "l": 37,
    "j": 38,
    "k": 40,
    "n": 45,
    "m": 46,
    "space": 49,
    "return": 36,
    "tab": 48,
    "escape": 53,
}


@dataclass(frozen=True)
class HotkeyDefinition:
    keycode: int
    modifiers: int


def parse_hotkey(hotkey: str) -> HotkeyDefinition:
    parts = [part.strip().lower() for part in hotkey.split("+") if part.strip()]
    if not parts:
        raise ValueError("Hotkey is empty")

    modifiers = 0
    keycode = None
    for part in parts:
        if part in MODIFIER_FLAGS:
            modifiers |= MODIFIER_FLAGS[part]
        else:
            keycode = KEYCODES.get(part)
            if keycode is None:
                raise ValueError(f"Unsupported hotkey key: {part}")

    if keycode is None:
        raise ValueError("Hotkey missing a primary key")
    return HotkeyDefinition(keycode=keycode, modifiers=modifiers)


class HotkeyListener:
    def __init__(self, hotkey: str, on_press, on_release) -> None:
        self.hotkey = parse_hotkey(hotkey)
        self.on_press = on_press
        self.on_release = on_release
        self._tap = None
        self._run_loop = None
        self._thread: threading.Thread | None = None
        self._pressed = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._run_loop is not None:
            CFRunLoopStop(self._run_loop)
        self._thread = None

    def _run(self) -> None:
        event_mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)
        self._tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            event_mask,
            self._callback,
            None,
        )
        if not self._tap:
            logger.error("Failed to create hotkey event tap")
            return
        run_loop = CFRunLoopGetCurrent()
        self._run_loop = run_loop
        source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        CFRunLoopAddSource(run_loop, source, kCFRunLoopCommonModes)
        CGEventTapEnable(self._tap, True)
        CFRunLoopRun()

    def _callback(self, proxy, event_type, event, refcon):
        if event_type not in (kCGEventKeyDown, kCGEventKeyUp):
            return event
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)
        if keycode != self.hotkey.keycode:
            return event
        if (flags & self.hotkey.modifiers) != self.hotkey.modifiers:
            return event

        if event_type == kCGEventKeyDown and not self._pressed:
            self._pressed = True
            self.on_press()
        elif event_type == kCGEventKeyUp and self._pressed:
            self._pressed = False
            self.on_release()
        return event
