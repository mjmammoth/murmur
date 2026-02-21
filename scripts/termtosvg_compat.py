#!/usr/bin/env python3
from __future__ import annotations

import inspect
import sys


def patch_pyte_report_device_status() -> None:
    """Patch pyte Screen.report_device_status to ignore unsupported kwargs.

    Some termtosvg + pyte combinations call `report_device_status(..., private=True)`
    while older Screen implementations do not accept `private`.
    """

    try:
        import pyte.screens as screens
    except Exception:
        return

    screen_cls = screens.Screen
    method = getattr(screen_cls, "report_device_status", None)
    if method is None:
        return

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        signature = None

    if signature and "private" in signature.parameters:
        return

    original = method

    def patched(self, *args, **kwargs):
        kwargs.pop("private", None)
        return original(self, *args, **kwargs)

    setattr(screen_cls, "report_device_status", patched)


def main() -> int:
    patch_pyte_report_device_status()

    try:
        from termtosvg.main import main as termtosvg_main
    except Exception as exc:  # pragma: no cover - runtime import guard
        print(f"Failed to import termtosvg: {exc}", file=sys.stderr)
        return 2

    termtosvg_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
