from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

# Force-mock AppKit and Quartz before importing hotkey module.
# Save originals so we can restore them after import.

_fake_appkit = types.ModuleType("AppKit")
_fake_appkit.NSEvent = MagicMock()  # type: ignore[attr-defined]

_fake_quartz = types.ModuleType("Quartz")
for _attr in (
    "CFRunLoopAddSource", "CFRunLoopGetCurrent", "CFRunLoopRun", "CFRunLoopStop",
    "CFMachPortCreateRunLoopSource", "CGEventGetFlags", "CGEventGetIntegerValueField",
    "CGEventMaskBit", "CGEventTapCreate", "CGEventTapEnable",
):
    setattr(_fake_quartz, _attr, MagicMock())

_fake_quartz.kCGEventFlagMaskAlternate = 0x80000  # type: ignore[attr-defined]
_fake_quartz.kCGEventFlagMaskCommand = 0x100000  # type: ignore[attr-defined]
_fake_quartz.kCGEventFlagMaskControl = 0x40000  # type: ignore[attr-defined]
_fake_quartz.kCGEventFlagMaskShift = 0x20000  # type: ignore[attr-defined]
_fake_quartz.kCGEventKeyDown = 10  # type: ignore[attr-defined]
_fake_quartz.kCGEventKeyUp = 11  # type: ignore[attr-defined]
_fake_quartz.kCGEventTapOptionDefault = 0  # type: ignore[attr-defined]
_fake_quartz.kCGHeadInsertEventTap = 0  # type: ignore[attr-defined]
_fake_quartz.kCGKeyboardEventKeycode = 9  # type: ignore[attr-defined]
_fake_quartz.kCGSessionEventTap = 1  # type: ignore[attr-defined]
_fake_quartz.kCFRunLoopCommonModes = MagicMock()  # type: ignore[attr-defined]

_saved_appkit = sys.modules.get("AppKit")
_saved_quartz = sys.modules.get("Quartz")
sys.modules["AppKit"] = _fake_appkit
sys.modules["Quartz"] = _fake_quartz

# Force a fresh import of the hotkey module with our mocks
_hotkey_key = "whisper_local.hotkey"
_saved_hotkey = sys.modules.pop(_hotkey_key, None)

from whisper_local.hotkey import (  # noqa: E402
    KEYCODES,
    MODIFIER_FLAGS,
    HotkeyDefinition,
    parse_hotkey,
)

# Restore original modules to avoid polluting other tests
if _saved_appkit is not None:
    sys.modules["AppKit"] = _saved_appkit
else:
    sys.modules.pop("AppKit", None)
if _saved_quartz is not None:
    sys.modules["Quartz"] = _saved_quartz
else:
    sys.modules.pop("Quartz", None)


# ---------------------------------------------------------------------------
# parse_hotkey
# ---------------------------------------------------------------------------

def test_parse_hotkey_single_key():
    hk = parse_hotkey("f7")
    assert hk.keycode == KEYCODES["f7"]
    assert hk.modifiers == 0


def test_parse_hotkey_key_with_modifier():
    hk = parse_hotkey("cmd+f")
    assert hk.keycode == KEYCODES["f"]
    assert hk.modifiers == MODIFIER_FLAGS["cmd"]


def test_parse_hotkey_multi_modifier():
    hk = parse_hotkey("ctrl+shift+a")
    assert hk.keycode == KEYCODES["a"]
    expected = MODIFIER_FLAGS["ctrl"] | MODIFIER_FLAGS["shift"]
    assert hk.modifiers == expected


def test_parse_hotkey_whitespace():
    hk = parse_hotkey("  cmd + f  ")
    assert hk.keycode == KEYCODES["f"]


def test_parse_hotkey_empty():
    with pytest.raises(ValueError, match="empty"):
        parse_hotkey("")


def test_parse_hotkey_unknown_key():
    with pytest.raises(ValueError, match="Unsupported"):
        parse_hotkey("cmd+nonexistent")


def test_parse_hotkey_modifiers_only():
    with pytest.raises(ValueError, match="missing a primary key"):
        parse_hotkey("cmd+shift")


# ---------------------------------------------------------------------------
# HotkeyDefinition dataclass
# ---------------------------------------------------------------------------

def test_hotkey_definition_frozen():
    hk = HotkeyDefinition(keycode=98, modifiers=0)
    assert hk.keycode == 98
    with pytest.raises(AttributeError):
        hk.keycode = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# KEYCODES and MODIFIER_FLAGS sanity checks
# ---------------------------------------------------------------------------

def test_keycodes_has_expected_entries():
    assert "a" in KEYCODES
    assert "space" in KEYCODES
    assert "f1" in KEYCODES
    assert "f12" in KEYCODES
    assert isinstance(KEYCODES["a"], int)


def test_modifier_flags_has_expected_entries():
    assert "cmd" in MODIFIER_FLAGS
    assert "ctrl" in MODIFIER_FLAGS
    assert "alt" in MODIFIER_FLAGS
    assert "shift" in MODIFIER_FLAGS
    assert MODIFIER_FLAGS["cmd"] == MODIFIER_FLAGS["command"]
    assert MODIFIER_FLAGS["ctrl"] == MODIFIER_FLAGS["control"]
    assert MODIFIER_FLAGS["alt"] == MODIFIER_FLAGS["option"]
