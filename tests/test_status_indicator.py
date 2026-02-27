from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch


# We need to mock macOS-only modules to import status_indicator on any platform.
# Strategy: temporarily replace sys.modules entries, import the module, then restore.

_MOCK_MODULES = {
    "objc": {"python_method": lambda f: f, "super": MagicMock()},
    "AppKit": {
        "NSApp": MagicMock(),
        "NSApplication": MagicMock(),
        "NSApplicationActivationPolicyAccessory": 0,
        "NSColor": MagicMock(),
        "NSForegroundColorAttributeName": "NSColor",
        "NSMenu": MagicMock(),
        "NSMenuItem": MagicMock(),
        "NSStatusBar": MagicMock(),
        "NSVariableStatusItemLength": -1,
    },
    "Foundation": {
        "NSMutableAttributedString": MagicMock(),
        "NSObject": type("NSObject", (), {}),
    },
    "PyObjCTools": {},
    "PyObjCTools.AppHelper": {
        "callAfter": MagicMock(),
        "runEventLoop": MagicMock(),
        "stopEventLoop": MagicMock(),
    },
    "websockets": {"connect": MagicMock()},
}

_saved_modules: dict[str, object] = {}
_installed_mocks: dict[str, types.ModuleType] = {}

for _name, _attrs in _MOCK_MODULES.items():
    _saved_modules[_name] = sys.modules.get(_name)
    _mod = types.ModuleType(_name)
    for _k, _v in _attrs.items():
        setattr(_mod, _k, _v)
    _installed_mocks[_name] = _mod
    sys.modules[_name] = _mod

# Wire up sub-package
_installed_mocks["PyObjCTools"].AppHelper = _installed_mocks["PyObjCTools.AppHelper"]  # type: ignore[attr-defined]

# Force fresh import
_si_key = "whisper_local.status_indicator"
_saved_si = sys.modules.pop(_si_key, None)

from whisper_local.status_indicator import build_parser, main  # noqa: E402

# Restore all original modules so we don't pollute other tests in the session
for _name, _orig in _saved_modules.items():
    if _orig is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _orig  # type: ignore[assignment]

# Don't restore status_indicator itself — we need the imported symbols to work.
# But the module's references are already bound to the fake objects, which is fine
# for our tests. Other test modules that import from the real status_indicator
# won't be affected because they'll trigger their own import.


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------

def test_build_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.host == "localhost"
    assert args.port == 7878


def test_build_parser_custom():
    parser = build_parser()
    args = parser.parse_args(["--host", "0.0.0.0", "--port", "9999"])
    assert args.host == "0.0.0.0"
    assert args.port == 9999


# ---------------------------------------------------------------------------
# main() on non-darwin
# ---------------------------------------------------------------------------

def test_main_non_darwin():
    with patch.object(sys.modules[_si_key], "sys") as mock_sys:
        mock_sys.platform = "linux"
        main()  # should return early without error
