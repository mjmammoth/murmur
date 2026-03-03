from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from AppKit import NSEvent
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
from murmur.platform.providers import PressReleaseCallback

# macOS NX_SYSDEFINED event type for media/special keys.
# When "Use F1, F2, etc. keys as standard function keys" is OFF (the default),
# pressing F7 sends a media key event (NX_SYSDEFINED) instead of kCGEventKeyDown.
NX_SYSDEFINED = 14


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
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}

# Map macOS media key types (NX_KEYTYPE_*) to F-key keycodes.
# These correspond to the default media functions printed on Apple keyboards.
MEDIA_KEY_TO_FKEY_KEYCODE = {
    3: 122,   # Brightness Down → F1
    2: 120,   # Brightness Up → F2
    # F3 (Mission Control) and F4 (Launchpad) use different event mechanisms
    22: 96,   # Illumination Down → F5
    21: 97,   # Illumination Up → F6
    18: 98,   # Previous Track → F7
    20: 98,   # Rewind (long-press) → F7
    16: 100,  # Play/Pause → F8
    17: 101,  # Next Track → F9
    19: 101,  # Fast Forward (long-press) → F9
    7: 109,   # Mute → F10
    1: 103,   # Volume Down → F11
    0: 111,   # Volume Up → F12
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
    def __init__(
        self,
        hotkey: str,
        on_press: PressReleaseCallback,
        on_release: PressReleaseCallback,
    ) -> None:
        self.hotkey = parse_hotkey(hotkey)
        self.on_press = on_press
        self.on_release = on_release
        self._tap: Any | None = None
        self._run_loop: Any | None = None
        self._thread: threading.Thread | None = None
        self._pressed = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._pressed = False
        if self._run_loop is not None:
            CFRunLoopStop(self._run_loop)
        self._thread = None

    def _run(self) -> None:
        event_mask = (
            CGEventMaskBit(kCGEventKeyDown)
            | CGEventMaskBit(kCGEventKeyUp)
            | CGEventMaskBit(NX_SYSDEFINED)
        )
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

    def _callback(self, proxy: Any, event_type: int, event: Any, refcon: Any) -> Any:
        del proxy, refcon
        if event_type == NX_SYSDEFINED:
            return self._handle_media_key(event)

        if event_type not in (kCGEventKeyDown, kCGEventKeyUp):
            return event

        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)

        if event_type == kCGEventKeyDown:
            if keycode != self.hotkey.keycode:
                return event
            if (flags & self.hotkey.modifiers) != self.hotkey.modifiers:
                return event

            if not self._pressed:
                self._pressed = True
                self.on_press()
            # Swallow matching keydown events to prevent echo in terminal/apps.
            return None

        # Key up handling is intentionally more permissive than key down:
        # users may release modifiers before releasing the main key.
        if self._pressed and keycode == self.hotkey.keycode:
            self._pressed = False
            self.on_release()
            return None

        # If a required modifier is released while we're pressed, treat that as release
        # for push-to-talk reliability on combos like shift+7.
        if self._pressed and self.hotkey.modifiers != 0:
            if (flags & self.hotkey.modifiers) != self.hotkey.modifiers:
                self._pressed = False
                self.on_release()

        return event

    def _handle_media_key(self, event: Any) -> Any:
        """Handle NX_SYSDEFINED media key events (F-keys without fn held)."""
        try:
            ns_event = NSEvent.eventWithCGEvent_(event)
            if ns_event is None or ns_event.subtype() != 8:
                return event

            data1 = ns_event.data1()
            media_key = (data1 >> 16) & 0xFF
            key_state = (data1 >> 8) & 0xFF
            # Bit 0 clear means key-down; bit 0 set means key-up.
            is_down = (key_state & 0x1) == 0

            keycode = MEDIA_KEY_TO_FKEY_KEYCODE.get(media_key)
            if keycode is None or keycode != self.hotkey.keycode:
                return event

            # Media keys carry no modifiers, so only match hotkeys without modifiers
            if self.hotkey.modifiers != 0:
                return event

            if is_down and not self._pressed:
                self._pressed = True
                self.on_press()
            elif not is_down and self._pressed:
                self._pressed = False
                self.on_release()
            return None  # Swallow the event
        except Exception:
            return event
