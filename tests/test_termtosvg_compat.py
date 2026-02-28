from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


def _load_termtosvg_compat_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "termtosvg_compat.py"
    spec = importlib.util.spec_from_file_location("termtosvg_compat", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module():
    return _load_termtosvg_compat_module()


def test_patch_pyte_report_device_status_when_pyte_unavailable(module) -> None:
    """Test that patch_pyte_report_device_status does nothing when pyte is not importable."""
    with patch.dict(sys.modules, {"pyte": None, "pyte.screens": None}):
        # Should not raise any exception
        module.patch_pyte_report_device_status()


def test_patch_pyte_report_device_status_when_method_missing(module) -> None:
    """Test that patch handles missing report_device_status method gracefully."""
    mock_screens = MagicMock()
    mock_screen_cls = MagicMock()
    mock_screen_cls.report_device_status = None
    mock_screens.Screen = mock_screen_cls

    mock_pyte = MagicMock()
    mock_pyte.screens = mock_screens
    with patch.dict(sys.modules, {"pyte": mock_pyte, "pyte.screens": mock_screens}):
        # Should not raise any exception
        module.patch_pyte_report_device_status()


def test_patch_pyte_report_device_status_when_signature_unavailable(module) -> None:
    """Test that patch handles methods without accessible signatures."""
    mock_screens = MagicMock()
    mock_screen_cls = type("Screen", (), {})

    def method_without_signature(self):
        pass

    # Make inspect.signature fail
    mock_method = Mock()
    mock_method.__name__ = "report_device_status"
    setattr(mock_screen_cls, "report_device_status", mock_method)

    mock_screens.Screen = mock_screen_cls

    mock_pyte = MagicMock()
    mock_pyte.screens = mock_screens
    with patch.dict(sys.modules, {"pyte": mock_pyte, "pyte.screens": mock_screens}):
        with patch("inspect.signature", side_effect=TypeError("Cannot inspect")):
            # Should not raise any exception
            module.patch_pyte_report_device_status()


def test_patch_pyte_report_device_status_when_private_param_exists(module) -> None:
    """Test that patch skips patching when 'private' parameter already exists."""
    mock_screens = MagicMock()
    mock_screen_cls = type("Screen", (), {})

    def report_device_status(self, private=False):
        return "has_private"

    setattr(mock_screen_cls, "report_device_status", report_device_status)
    mock_screens.Screen = mock_screen_cls

    mock_pyte = MagicMock()
    mock_pyte.screens = mock_screens
    with patch.dict(sys.modules, {"pyte": mock_pyte, "pyte.screens": mock_screens}):
        module.patch_pyte_report_device_status()
        # Method should remain unchanged
        instance = mock_screen_cls()
        assert instance.report_device_status(private=True) == "has_private"


def test_patch_pyte_report_device_status_applies_wrapper(module) -> None:
    """Test that patch wrapper logic strips 'private' parameter."""
    original_called_with = []

    def original_report(self, *args, **kwargs):
        original_called_with.append((args, kwargs))
        return "original_result"

    mock_screens = MagicMock()
    mock_screen_cls = type("Screen", (), {"report_device_status": original_report})
    mock_screens.Screen = mock_screen_cls

    mock_pyte = MagicMock()
    mock_pyte.screens = mock_screens
    with patch.dict(sys.modules, {"pyte": mock_pyte, "pyte.screens": mock_screens}):
        module.patch_pyte_report_device_status()

    instance = mock_screen_cls()
    result = instance.report_device_status(arg1="value", private=True, arg2="value2")

    assert len(original_called_with) == 1
    args, kwargs = original_called_with[0]
    assert "private" not in kwargs
    assert kwargs.get("arg1") == "value"
    assert kwargs.get("arg2") == "value2"
    assert result == "original_result"


def test_patch_pyte_report_device_status_preserves_args(module) -> None:
    """Test that patched wrapper preserves positional arguments."""
    captured_calls = []

    def original_report(self, *args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        return "result"

    mock_screens = MagicMock()
    mock_screen_cls = type("Screen", (), {"report_device_status": original_report})
    mock_screens.Screen = mock_screen_cls

    mock_pyte = MagicMock()
    mock_pyte.screens = mock_screens
    with patch.dict(sys.modules, {"pyte": mock_pyte, "pyte.screens": mock_screens}):
        module.patch_pyte_report_device_status()

    instance = mock_screen_cls()
    instance.report_device_status("pos1", "pos2", kwarg1="val1", private=True)

    assert len(captured_calls) == 1
    assert captured_calls[0]["args"] == ("pos1", "pos2")
    assert captured_calls[0]["kwargs"] == {"kwarg1": "val1"}


def test_main_imports_and_runs_termtosvg(module) -> None:
    """Test that main successfully imports and runs termtosvg."""
    mock_termtosvg_main = Mock(return_value=0)

    with patch.dict(sys.modules, {"termtosvg.main": Mock(main=mock_termtosvg_main)}):
        result = module.main()

        assert result == 0
        mock_termtosvg_main.assert_called_once()


def test_main_handles_termtosvg_import_failure(module, capsys) -> None:
    """Test that main returns error code when termtosvg import fails."""
    with patch.dict(sys.modules, {"termtosvg.main": None}):
        with patch("builtins.__import__", side_effect=ImportError("termtosvg not found")):
            result = module.main()

            assert result == 2
            captured = capsys.readouterr()
            assert "Failed to import termtosvg" in captured.err


def test_main_handles_systemexit_with_none_code(module) -> None:
    """Test that main returns 0 when termtosvg raises SystemExit with None code."""
    mock_termtosvg_main = Mock(side_effect=SystemExit(None))

    with patch.dict(sys.modules, {"termtosvg.main": Mock(main=mock_termtosvg_main)}):
        result = module.main()

        assert result == 0


def test_main_handles_systemexit_with_int_code(module) -> None:
    """Test that main returns the exit code when termtosvg raises SystemExit with int."""
    mock_termtosvg_main = Mock(side_effect=SystemExit(42))

    with patch.dict(sys.modules, {"termtosvg.main": Mock(main=mock_termtosvg_main)}):
        result = module.main()

        assert result == 42


def test_main_handles_systemexit_with_non_int_code(module) -> None:
    """Test that main returns 1 when termtosvg raises SystemExit with non-int code."""
    mock_termtosvg_main = Mock(side_effect=SystemExit("error message"))

    with patch.dict(sys.modules, {"termtosvg.main": Mock(main=mock_termtosvg_main)}):
        result = module.main()

        assert result == 1


def test_main_handles_generic_exception(module, capsys) -> None:
    """Test that main returns 2 when termtosvg raises a generic exception."""
    mock_termtosvg_main = Mock(side_effect=RuntimeError("Something went wrong"))

    with patch.dict(sys.modules, {"termtosvg.main": Mock(main=mock_termtosvg_main)}):
        result = module.main()

        assert result == 2
        captured = capsys.readouterr()
        assert "termtosvg failed" in captured.err


def test_main_returns_int_result_from_termtosvg(module) -> None:
    """Test that main returns integer result from termtosvg when provided."""
    mock_termtosvg_main = Mock(return_value=5)

    with patch.dict(sys.modules, {"termtosvg.main": Mock(main=mock_termtosvg_main)}):
        result = module.main()

        assert result == 5


def test_main_returns_zero_for_non_int_result(module) -> None:
    """Test that main returns 0 when termtosvg returns non-int value."""
    mock_termtosvg_main = Mock(return_value="success")

    with patch.dict(sys.modules, {"termtosvg.main": Mock(main=mock_termtosvg_main)}):
        result = module.main()

        assert result == 0


def test_main_applies_patch_before_import(module) -> None:
    """Test that patch_pyte_report_device_status is called before importing termtosvg."""
    patch_called = []

    def mock_patch():
        patch_called.append(True)

    mock_termtosvg_main = Mock(return_value=0)

    with patch.object(module, "patch_pyte_report_device_status", side_effect=mock_patch):
        with patch.dict(sys.modules, {"termtosvg.main": Mock(main=mock_termtosvg_main)}):
            result = module.main()

    # Patch should be called
    assert len(patch_called) == 1
    assert result == 0
    mock_termtosvg_main.assert_called_once()
