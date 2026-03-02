from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pyperclip


logger = logging.getLogger(__name__)


@dataclass
class ClipboardSnapshot:
    """Best-effort snapshot of clipboard content for restore after auto-paste."""

    macos_items: list[dict[str, bytes]] | None
    text: str | None


def _clipboard_text_snapshot() -> str | None:
    """
    Capture a best-effort plain-text snapshot of the system clipboard.

    Returns:
        The clipboard text as a string if available, `None` otherwise.
    """
    try:
        return cast(str | None, pyperclip.paste())
    except pyperclip.PyperclipException as exc:
        logger.debug("Clipboard paste snapshot unavailable: %s", exc)
        return None


def _extract_pasteboard_item_data(item: Any) -> dict[str, bytes]:
    """Extract type-to-bytes mapping from a single pasteboard item."""
    type_data: dict[str, bytes] = {}
    try:
        item_types = item.types() or []
    except Exception:
        return {}
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
    return type_data


def _clipboard_macos_snapshot() -> list[dict[str, bytes]] | None:
    """
    Capture a best-effort snapshot of the macOS system pasteboard, returning raw data for each pasteboard item.

    If not running on macOS or if pasteboard access (AppKit) is unavailable or fails, returns None. If the pasteboard is accessible but contains no items, returns an empty list.

    Returns:
        list[dict[str, bytes]] | None: A list where each element is a mapping from pasteboard type identifier (string) to the raw bytes payload for that item, or None when macOS pasteboard access is unsupported or failed.
    """
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
        type_data = _extract_pasteboard_item_data(item)
        if type_data:
            snapshot.append(type_data)
    return snapshot


def _restore_macos_snapshot(items: list[dict[str, bytes]]) -> bool:
    """
    Restore the macOS pasteboard from a list of pasteboard item payloads.

    Parameters:
        items (list[dict[str, bytes]]): A list of pasteboard items; each item is a mapping from pasteboard type identifier
            (e.g., a UTI or pasteboard type string) to its raw bytes payload.

    Returns:
        bool: `True` if the pasteboard was successfully written, `False` otherwise (including when not running on macOS).
    """
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
        if not pasteboard_items:
            return False
        success = bool(pasteboard.writeObjects_(pasteboard_items))
        return success
    except Exception as exc:
        logger.warning("Clipboard macOS restore failed: %s", exc)
        return False


def capture_clipboard_snapshot() -> ClipboardSnapshot:
    """
    Capture a best-effort snapshot of the current clipboard contents.

    The returned snapshot includes macOS-specific pasteboard items when available and a plain-text snapshot when obtainable.

    Returns:
        snapshot (ClipboardSnapshot): Snapshot with `macos_items` set to a list of dicts mapping pasteboard types to bytes when available (or `None` on non-macOS or failure), and `text` set to the clipboard text string when available (or `None` if unavailable).
    """
    return ClipboardSnapshot(
        macos_items=_clipboard_macos_snapshot(),
        text=_clipboard_text_snapshot(),
    )


def restore_clipboard_snapshot(snapshot: ClipboardSnapshot | None) -> bool:
    """
    Restore a previously captured clipboard snapshot, preferring macOS pasteboard items when available.

    If the snapshot contains macOS-specific pasteboard items and they are successfully restored, the function returns `True`. If no macOS items are restored but a text snapshot is present, the function restores the text to the clipboard. A `None` snapshot or any restoration failure results in `False`.

    Parameters:
        snapshot (ClipboardSnapshot | None): The snapshot to restore; may contain macOS pasteboard items and/or a plain-text snapshot.

    Returns:
        bool: `True` if the clipboard was restored, `False` otherwise.
    """
    if snapshot is None:
        return False

    if snapshot.macos_items and _restore_macos_snapshot(snapshot.macos_items):
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
    """
    Copy the given text into the system clipboard.

    Returns:
        True if the text was successfully copied, False if the copy failed (for example, when the clipboard is unavailable).
    """
    try:
        pyperclip.copy(text)
        return True
    except pyperclip.PyperclipException as exc:
        logger.warning("Clipboard copy failed: %s", exc)
        return False


def paste_from_clipboard() -> bool:
    """
    Paste current clipboard contents into the focused macOS application.

    This requires macOS Accessibility permission for the calling terminal or application
    (System Settings → Privacy & Security → Accessibility) so osascript can simulate Command+V.

    Returns:
        `True` if the paste simulation succeeded, `False` otherwise.
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
