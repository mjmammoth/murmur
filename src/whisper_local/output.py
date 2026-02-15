from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pyperclip


logger = logging.getLogger(__name__)


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
