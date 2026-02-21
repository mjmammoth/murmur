from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pyperclip


logger = logging.getLogger(__name__)


@dataclass
class ClipboardSnapshot:
    """Best-effort snapshot of clipboard content for restore after auto-paste."""

    macos_items: list[dict[str, bytes]] | None
    text: str | None


def _clipboard_text_snapshot() -> str | None:
    try:
        return pyperclip.paste()
    except pyperclip.PyperclipException as exc:
        logger.debug("Clipboard paste snapshot unavailable: %s", exc)
        return None


def _clipboard_macos_snapshot() -> list[dict[str, bytes]] | None:
    if sys.platform != "darwin":
        return None

    try:
        from AppKit import NSPasteboard
    except Exception as exc:
        logger.debug("Clipboard macOS snapshot unavailable: %s", exc)
        return None

    try:
        pasteboard = NSPasteboard.generalPasteboard()
        items = pasteboard.pasteboardItems()
    except Exception as exc:
        logger.warning("Clipboard macOS snapshot failed: %s", exc)
        return None

    if not items:
        return []

    snapshot: list[dict[str, bytes]] = []
    for item in items:
        type_data: dict[str, bytes] = {}
        item_types = item.types() or []
        for item_type in item_types:
            try:
                payload = item.dataForType_(item_type)
            except Exception:
                continue
            if payload is None:
                continue
            try:
                data_bytes = bytes(payload)
            except Exception:
                continue
            type_data[str(item_type)] = data_bytes
        snapshot.append(type_data)
    return snapshot


def _restore_macos_snapshot(items: list[dict[str, bytes]]) -> bool:
    if sys.platform != "darwin":
        return False

    try:
        from AppKit import NSPasteboard, NSPasteboardItem
        from Foundation import NSData
    except Exception as exc:
        logger.debug("Clipboard macOS restore unavailable: %s", exc)
        return False

    try:
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard_items = []
        for item in items:
            pasteboard_item = NSPasteboardItem.alloc().init()
            for item_type, payload in item.items():
                ns_data = NSData.dataWithBytes_length_(payload, len(payload))
                pasteboard_item.setData_forType_(ns_data, item_type)
            pasteboard_items.append(pasteboard_item)
        if pasteboard_items:
            pasteboard.writeObjects_(pasteboard_items)
        return True
    except Exception as exc:
        logger.warning("Clipboard macOS restore failed: %s", exc)
        return False


def capture_clipboard_snapshot() -> ClipboardSnapshot:
    return ClipboardSnapshot(
        macos_items=_clipboard_macos_snapshot(),
        text=_clipboard_text_snapshot(),
    )


def restore_clipboard_snapshot(snapshot: ClipboardSnapshot | None) -> bool:
    if snapshot is None:
        return False

    if snapshot.macos_items is not None and _restore_macos_snapshot(snapshot.macos_items):
        return True

    if snapshot.text is None:
        return False

    try:
        pyperclip.copy(snapshot.text)
        return True
    except pyperclip.PyperclipException as exc:
        logger.warning("Clipboard text restore failed: %s", exc)
        return False


def copy_to_clipboard(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except pyperclip.PyperclipException as exc:
        logger.warning("Clipboard copy failed: %s", exc)
        return False


def paste_from_clipboard() -> bool:
    """Paste current clipboard contents into the focused macOS app.
    
    Requires macOS Accessibility permission (System Settings → Privacy & Security → Accessibility)
    for the terminal or app running whisper.local to allow osascript to simulate Cmd+V.
    """
    if sys.platform != "darwin":
        logger.warning("Auto paste is currently supported only on macOS")
        return False

    try:
        subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using command down',
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except FileNotFoundError:
        logger.warning("Auto paste failed: osascript is not available")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip().lower()
        # Check for macOS Accessibility permission errors
        if any(keyword in detail for keyword in ["not permitted", "ax", "accessibility", "permission"]):
            logger.warning(
                "Auto paste failed: macOS Accessibility permission required. "
                "Please grant Accessibility permission to the terminal/app in "
                "System Settings → Privacy & Security → Accessibility. "
                "Error: %s",
                detail,
            )
        else:
            logger.warning("Auto paste failed: %s", detail)
    except OSError as exc:
        exc_str = str(exc).lower()
        if any(keyword in exc_str for keyword in ["not permitted", "ax", "accessibility", "permission"]):
            logger.warning(
                "Auto paste failed: macOS Accessibility permission required. "
                "Please grant Accessibility permission to the terminal/app in "
                "System Settings → Privacy & Security → Accessibility. "
                "Error: %s",
                exc,
            )
        else:
            logger.warning("Auto paste failed: %s", exc)
    return False


def append_to_file(path: Path, text: str) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")
