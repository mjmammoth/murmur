from __future__ import annotations

import logging
import os
import sys
from importlib import import_module

from whisper_local.platform.capabilities import PlatformCapabilities
from whisper_local.platform.providers import (
    DefaultPasteProvider,
    HotkeyProvider,
    MacOSHotkeyProvider,
    NoopHotkeyProvider,
    NoopPasteProvider,
    NoopStatusIndicatorProvider,
    PasteProvider,
    PressReleaseCallback,
    StatusIndicatorProvider,
    SubprocessStatusIndicatorProvider,
    WindowsHotkeyProvider,
    X11HotkeyProvider,
)


logger = logging.getLogger(__name__)


MODIFIER_ALIASES = {
    "cmd": "cmd",
    "command": "cmd",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
}

HOTKEY_KEYS = {
    "a",
    "s",
    "d",
    "f",
    "h",
    "g",
    "z",
    "x",
    "c",
    "v",
    "b",
    "q",
    "w",
    "e",
    "r",
    "y",
    "t",
    "1",
    "2",
    "3",
    "4",
    "6",
    "5",
    "9",
    "7",
    "8",
    "0",
    "o",
    "u",
    "i",
    "p",
    "l",
    "j",
    "k",
    "n",
    "m",
    "space",
    "return",
    "tab",
    "escape",
    "f1",
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
    "f9",
    "f10",
    "f11",
    "f12",
}

def _is_wayland_session() -> bool:
    return (
        os.environ.get("XDG_SESSION_TYPE", "").strip().lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY", "").strip())
    )


def _has_x11_display() -> bool:
    return bool(os.environ.get("DISPLAY", "").strip())


def parse_hotkey_tokens(hotkey: str) -> tuple[tuple[str, ...], str]:
    parts = [part.strip().lower() for part in hotkey.split("+") if part.strip()]
    if not parts:
        raise ValueError("Hotkey is empty")

    modifiers: list[str] = []
    primary_key: str | None = None

    for part in parts:
        if part in MODIFIER_ALIASES:
            normalized_modifier = MODIFIER_ALIASES[part]
            if normalized_modifier not in modifiers:
                modifiers.append(normalized_modifier)
            continue

        if part not in HOTKEY_KEYS:
            raise ValueError(f"Unsupported hotkey key: {part}")
        if primary_key is not None:
            raise ValueError("Hotkey must include exactly one primary key")
        primary_key = part

    if primary_key is None:
        raise ValueError("Hotkey missing a primary key")

    return tuple(modifiers), primary_key


def validate_hotkey(hotkey: str) -> None:
    parse_hotkey_tokens(hotkey)


def _x11_hotkey_runtime_status() -> tuple[bool, str | None]:
    if not _has_x11_display():
        return False, "No X11 display detected. Configure DISPLAY or use trigger fallback."

    try:
        import_module("Xlib.display")
        import_module("Xlib.XK")
    except Exception:
        return False, "python-xlib is unavailable. Install with: python -m pip install python-xlib"

    return True, None


def _windows_hotkey_runtime_status() -> tuple[bool, str | None]:
    try:
        import_module("win32api")
        import_module("win32con")
        import_module("win32gui")
    except Exception:
        return False, "pywin32 is unavailable. Install with: python -m pip install pywin32"

    return True, None


def detect_platform_capabilities() -> PlatformCapabilities:
    if sys.platform == "darwin":
        return PlatformCapabilities(
            hotkey_capture=True,
            hotkey_swallow=True,
            status_indicator=True,
            auto_paste=True,
            hotkey_guidance=None,
        )

    if sys.platform.startswith("linux"):
        if _is_wayland_session():
            return PlatformCapabilities(
                hotkey_capture=False,
                hotkey_swallow=False,
                status_indicator=False,
                auto_paste=False,
                hotkey_guidance=(
                    "Wayland does not guarantee global key swallowing. "
                    "Bind a desktop shortcut to 'murmur trigger toggle'."
                ),
            )

        hotkey_available, reason = _x11_hotkey_runtime_status()
        if hotkey_available:
            return PlatformCapabilities(
                hotkey_capture=True,
                hotkey_swallow=True,
                status_indicator=False,
                auto_paste=False,
                hotkey_guidance=None,
            )

        guidance = reason or (
            "X11 hotkey capture unavailable. "
            "Bind a desktop shortcut to 'murmur trigger toggle'."
        )
        return PlatformCapabilities(
            hotkey_capture=False,
            hotkey_swallow=False,
            status_indicator=False,
            auto_paste=False,
            hotkey_guidance=guidance,
        )

    if sys.platform in {"win32", "cygwin", "msys"}:
        hotkey_available, reason = _windows_hotkey_runtime_status()
        if hotkey_available:
            return PlatformCapabilities(
                hotkey_capture=True,
                hotkey_swallow=True,
                status_indicator=False,
                auto_paste=False,
                hotkey_guidance=None,
            )

        return PlatformCapabilities(
            hotkey_capture=False,
            hotkey_swallow=False,
            status_indicator=False,
            auto_paste=False,
            hotkey_guidance=reason or "Windows hotkey runtime unavailable.",
        )

    return PlatformCapabilities(
        hotkey_capture=False,
        hotkey_swallow=False,
        status_indicator=False,
        auto_paste=False,
        hotkey_guidance="Unsupported platform for native hotkey capture.",
    )


def create_hotkey_provider(
    hotkey: str,
    on_press: PressReleaseCallback,
    on_release: PressReleaseCallback,
) -> HotkeyProvider:
    modifiers, key = parse_hotkey_tokens(hotkey)

    if sys.platform == "darwin":
        logger.info("Hotkey backend selected: macOS")
        return MacOSHotkeyProvider(hotkey=hotkey, on_press=on_press, on_release=on_release)

    if sys.platform.startswith("linux"):
        if _is_wayland_session():
            logger.info("Hotkey backend selected: noop (wayland session)")
            return NoopHotkeyProvider(
                reason=(
                    "Wayland does not guarantee global key swallowing. "
                    "Bind a desktop shortcut to 'murmur trigger toggle'."
                )
            )

        hotkey_available, reason = _x11_hotkey_runtime_status()
        if hotkey_available:
            logger.info("Hotkey backend selected: X11")
            return X11HotkeyProvider(
                key=key,
                modifiers=modifiers,
                on_press=on_press,
                on_release=on_release,
            )
        logger.info("Hotkey backend selected: noop (X11 unavailable)")
        return NoopHotkeyProvider(reason=reason)

    if sys.platform in {"win32", "cygwin", "msys"}:
        hotkey_available, reason = _windows_hotkey_runtime_status()
        if hotkey_available:
            logger.info("Hotkey backend selected: Windows")
            return WindowsHotkeyProvider(
                key=key,
                modifiers=modifiers,
                on_press=on_press,
                on_release=on_release,
            )
        logger.info("Hotkey backend selected: noop (Windows runtime unavailable)")
        return NoopHotkeyProvider(reason=reason)

    capabilities = detect_platform_capabilities()
    logger.info("Hotkey backend selected: noop (unsupported platform)")
    return NoopHotkeyProvider(reason=capabilities.hotkey_guidance)


def create_status_indicator_provider(
    *,
    host: str,
    port: int,
    python_executable: str | None = None,
) -> StatusIndicatorProvider:
    capabilities = detect_platform_capabilities()
    if capabilities.status_indicator:
        return SubprocessStatusIndicatorProvider(
            host=host,
            port=port,
            python_executable=python_executable,
        )
    return NoopStatusIndicatorProvider()


def create_paste_provider() -> PasteProvider:
    capabilities = detect_platform_capabilities()
    if capabilities.auto_paste:
        return DefaultPasteProvider()
    return NoopPasteProvider()
