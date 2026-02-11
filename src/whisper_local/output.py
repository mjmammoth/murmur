from __future__ import annotations

import logging
from pathlib import Path

import pyperclip


logger = logging.getLogger(__name__)


def copy_to_clipboard(text: str) -> None:
    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as exc:
        logger.warning("Clipboard copy failed: %s", exc)


def append_to_file(path: Path, text: str) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")
