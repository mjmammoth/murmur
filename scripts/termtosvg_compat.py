#!/usr/bin/env python3
from __future__ import annotations

import inspect
import sys


def patch_pyte_report_device_status() -> None:
    """
    Patch pyte.screens.Screen.report_device_status to drop an unsupported 'private' keyword argument when present.

    If pyte or the Screen.report_device_status method is unavailable, or if the method already accepts a `private` parameter, the function leaves nothing changed. Otherwise it replaces the method with a wrapper that removes the `private` keyword from kwargs before delegating to the original implementation.
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
        """
        Wrapper for Screen.report_device_status that removes an unsupported `private` keyword from kwargs before calling the original method.

        Returns:
            The value returned by the original `report_device_status` implementation.
        """
        kwargs.pop("private", None)
        return original(self, *args, **kwargs)

    setattr(screen_cls, "report_device_status", patched)


def main() -> int:
    """
    Run compatibility patch then invoke termtosvg's main entry point and return an appropriate process exit code.

    Applies a compatibility patch to pyte (if needed), attempts to import and call termtosvg.main.main, and maps its outcomes to conventional process exit codes: returns the integer result returned by termtosvg when it is an int; if termtosvg raises SystemExit, returns 0 when the exit code is None, the integer code when it is an int, or 1 for non-integer codes; returns 2 if importing or running termtosvg fails.

    Returns:
        int: Process-style exit code as described above.
    """
    patch_pyte_report_device_status()

    try:
        from termtosvg.main import main as termtosvg_main
    except Exception as exc:  # pragma: no cover - runtime import guard
        print(f"Failed to import termtosvg: {exc}", file=sys.stderr)
        return 2

    try:
        result = termtosvg_main()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        if code is None:
            return 0
        return 1
    except Exception as exc:  # pragma: no cover - runtime passthrough guard
        print(f"termtosvg failed: {exc}", file=sys.stderr)
        return 2

    if isinstance(result, int):
        return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
