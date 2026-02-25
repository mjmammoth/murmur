from __future__ import annotations

from unittest.mock import Mock, patch

from whisper_local.platform.providers import (
    NoopHotkeyProvider,
    WindowsHotkeyProvider,
    X11HotkeyProvider,
    _windows_modifier_mask,
    _windows_vk_code,
    _x11_keysym_name,
)


def test_x11_keysym_name_maps_special_keys():
    assert _x11_keysym_name("f3") == "F3"
    assert _x11_keysym_name("return") == "Return"
    assert _x11_keysym_name("space") == "space"


def test_windows_vk_code_maps_special_keys():
    assert _windows_vk_code("return") == 0x0D
    assert _windows_vk_code("tab") == 0x09
    assert _windows_vk_code("escape") == 0x1B
    assert _windows_vk_code("f1") == 0x70


def test_windows_modifier_mask_maps_known_modifiers():
    win32con = type(
        "Win32Con",
        (),
        {
            "MOD_ALT": 0x0001,
            "MOD_CONTROL": 0x0002,
            "MOD_SHIFT": 0x0004,
            "MOD_WIN": 0x0008,
        },
    )

    mask = _windows_modifier_mask(("alt", "ctrl", "shift", "cmd"), win32con)

    assert mask == 0x000F


def test_noop_hotkey_provider_logs_reason_on_start():
    provider = NoopHotkeyProvider(reason="not available")

    with patch("whisper_local.platform.providers.logger") as mock_logger:
        provider.start()

    mock_logger.info.assert_called_once()


def test_x11_provider_start_stop_idempotent():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)

    thread = Mock()
    thread.is_alive.return_value = True

    with patch("whisper_local.platform.providers.threading.Thread", return_value=thread) as mock_thread_ctor:
        provider.start()
        provider.start()
        provider.stop()

    mock_thread_ctor.assert_called_once()
    thread.start.assert_called_once()


def test_windows_provider_parses_constructor_values():
    provider = WindowsHotkeyProvider(
        key="f3",
        modifiers=("ctrl",),
        on_press=lambda: None,
        on_release=lambda: None,
    )

    assert provider._vk_code == 0x72


def test_windows_provider_is_hotkey_down_checks_modifiers():
    provider = WindowsHotkeyProvider(
        key="f3",
        modifiers=("ctrl", "shift"),
        on_press=lambda: None,
        on_release=lambda: None,
    )

    values = {
        provider._vk_code: 0x8000,
        0x11: 0x8000,  # VK_CONTROL
        0x10: 0x8000,  # VK_SHIFT
        0x12: 0x0000,  # VK_MENU
        0x5B: 0x0000,  # VK_LWIN
        0x5C: 0x0000,  # VK_RWIN
    }

    win32api = Mock()
    win32api.GetAsyncKeyState.side_effect = lambda vk: values.get(vk, 0)
    win32con = type(
        "Win32Con",
        (),
        {
            "VK_CONTROL": 0x11,
            "VK_SHIFT": 0x10,
            "VK_MENU": 0x12,
            "VK_LWIN": 0x5B,
            "VK_RWIN": 0x5C,
        },
    )

    assert provider._is_hotkey_down(win32api, win32con) is True
