from __future__ import annotations

from murmur.platform import factory
from murmur.platform.providers import NoopHotkeyProvider, WindowsHotkeyProvider, X11HotkeyProvider


class _DummyModule:
    pass


def _fake_import_module_success(name: str):
    del name
    return _DummyModule()


def test_detect_platform_capabilities_darwin(monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "darwin")

    caps = factory.detect_platform_capabilities()

    assert caps.hotkey_capture is True
    assert caps.hotkey_swallow is True
    assert caps.status_indicator is True
    assert caps.auto_paste is True


def test_detect_platform_capabilities_wayland(monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    caps = factory.detect_platform_capabilities()

    assert caps.hotkey_capture is False
    assert caps.hotkey_swallow is False
    assert caps.status_indicator is False
    assert caps.auto_paste is False
    assert caps.hotkey_guidance is not None
    assert "trigger toggle" in caps.hotkey_guidance


def test_detect_platform_capabilities_x11_available(monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "linux")
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(factory, "import_module", _fake_import_module_success)

    caps = factory.detect_platform_capabilities()

    assert caps.hotkey_capture is True
    assert caps.hotkey_swallow is True
    assert caps.hotkey_guidance is None


def test_detect_platform_capabilities_x11_missing_runtime(monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "linux")
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")

    def _fake_import_module_fail(name: str):
        raise ImportError(name)

    monkeypatch.setattr(factory, "import_module", _fake_import_module_fail)

    caps = factory.detect_platform_capabilities()

    assert caps.hotkey_capture is False
    assert caps.hotkey_swallow is False
    assert caps.hotkey_guidance is not None
    assert "python-xlib" in caps.hotkey_guidance


def test_detect_platform_capabilities_windows_available(monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "win32")
    monkeypatch.setattr(factory, "import_module", _fake_import_module_success)

    caps = factory.detect_platform_capabilities()

    assert caps.hotkey_capture is True
    assert caps.hotkey_swallow is True
    assert caps.status_indicator is False
    assert caps.auto_paste is False


def test_create_hotkey_provider_linux_x11_returns_x11_provider(monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "linux")
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(factory, "import_module", _fake_import_module_success)

    provider = factory.create_hotkey_provider("ctrl+f3", lambda: None, lambda: None)

    assert isinstance(provider, X11HotkeyProvider)


def test_create_hotkey_provider_windows_returns_windows_provider(monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "win32")
    monkeypatch.setattr(factory, "import_module", _fake_import_module_success)

    provider = factory.create_hotkey_provider("ctrl+f3", lambda: None, lambda: None)

    assert isinstance(provider, WindowsHotkeyProvider)


def test_create_hotkey_provider_windows_missing_runtime_returns_noop(monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "win32")

    def _fake_import_module_fail(name: str):
        raise ImportError(name)

    monkeypatch.setattr(factory, "import_module", _fake_import_module_fail)

    provider = factory.create_hotkey_provider("ctrl+f3", lambda: None, lambda: None)

    assert isinstance(provider, NoopHotkeyProvider)


def test_parse_hotkey_tokens_normalizes_modifiers():
    modifiers, key = factory.parse_hotkey_tokens("control+option+f3")

    assert modifiers == ("ctrl", "alt")
    assert key == "f3"


def test_validate_hotkey_accepts_modifier_combo():
    factory.validate_hotkey("ctrl+shift+f3")


def test_validate_hotkey_rejects_multiple_primary_keys():
    try:
        factory.validate_hotkey("a+b")
    except ValueError as exc:
        assert "exactly one primary key" in str(exc)
        return
    raise AssertionError("Expected validate_hotkey to reject multiple primary keys")
