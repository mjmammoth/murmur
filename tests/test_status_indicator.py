from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


_SI_KEY = "whisper_local.status_indicator"
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


@pytest.fixture(scope="module", autouse=True)
def mock_macos_modules():
    saved_modules: dict[str, object] = {}
    installed_mocks: dict[str, types.ModuleType] = {}
    for name, attrs in _MOCK_MODULES.items():
        saved_modules[name] = sys.modules.get(name)
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        installed_mocks[name] = module
        sys.modules[name] = module

    installed_mocks["PyObjCTools"].AppHelper = installed_mocks["PyObjCTools.AppHelper"]  # type: ignore[attr-defined]
    saved_si = sys.modules.pop(_SI_KEY, None)
    try:
        yield
    finally:
        for name, original_module in saved_modules.items():
            if original_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original_module  # type: ignore[assignment]
        if saved_si is not None:
            sys.modules[_SI_KEY] = saved_si
        else:
            sys.modules.pop(_SI_KEY, None)


@pytest.fixture(scope="module")
def status_indicator_module():
    return importlib.import_module(_SI_KEY)


def test_build_parser_defaults(status_indicator_module):
    parser = status_indicator_module.build_parser()
    args = parser.parse_args([])
    assert args.host == "localhost"
    assert args.port == 7878


def test_build_parser_custom(status_indicator_module):
    parser = status_indicator_module.build_parser()
    args = parser.parse_args(["--host", "0.0.0.0", "--port", "9999"])
    assert args.host == "0.0.0.0"
    assert args.port == 9999


def test_main_non_darwin(status_indicator_module):
    with patch.object(status_indicator_module, "sys") as mock_sys, patch.object(
        status_indicator_module, "NSApplication"
    ) as mock_ns_application:
        mock_sys.platform = "linux"
        status_indicator_module.main()

    mock_ns_application.sharedApplication.assert_not_called()
