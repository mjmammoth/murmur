from __future__ import annotations

import subprocess
from unittest.mock import Mock, MagicMock, patch

import pytest

from whisper_local.platform.providers import (
    DefaultPasteProvider,
    HotkeyProvider,
    NoopHotkeyProvider,
    NoopPasteProvider,
    NoopStatusIndicatorProvider,
    PasteProvider,
    StatusIndicatorProvider,
    SubprocessStatusIndicatorProvider,
    WindowsHotkeyProvider,
    X11HotkeyProvider,
    _windows_modifier_mask,
    _windows_vk_code,
    _x11_keysym_name,
    _x11_modifier_mask,
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


# ---------------------------------------------------------------------------
# _x11_keysym_name — additional cases
# ---------------------------------------------------------------------------

def test_x11_keysym_name_fkeys():
    assert _x11_keysym_name("f1") == "F1"
    assert _x11_keysym_name("f12") == "F12"


def test_x11_keysym_name_tab_escape():
    assert _x11_keysym_name("tab") == "Tab"
    assert _x11_keysym_name("escape") == "Escape"


def test_x11_keysym_name_unknown_passthrough():
    assert _x11_keysym_name("z") == "z"


# ---------------------------------------------------------------------------
# _x11_modifier_mask
# ---------------------------------------------------------------------------

def test_x11_modifier_mask_combos():
    xlib_x = type("X", (), {
        "ShiftMask": 1,
        "ControlMask": 4,
        "Mod1Mask": 8,
        "Mod4Mask": 64,
    })
    assert _x11_modifier_mask(("shift",), xlib_x) == 1
    assert _x11_modifier_mask(("ctrl", "alt"), xlib_x) == 12
    assert _x11_modifier_mask(("cmd",), xlib_x) == 64
    assert _x11_modifier_mask(("unknown",), xlib_x) == 0


# ---------------------------------------------------------------------------
# _windows_vk_code — additional cases
# ---------------------------------------------------------------------------

def test_windows_vk_code_single_char():
    assert _windows_vk_code("a") == ord("A")
    assert _windows_vk_code("z") == ord("Z")


def test_windows_vk_code_space():
    assert _windows_vk_code("space") == 0x20


def test_windows_vk_code_unsupported():
    with pytest.raises(ValueError, match="Unsupported"):
        _windows_vk_code("nonexistent")


# ---------------------------------------------------------------------------
# _windows_modifier_mask — additional
# ---------------------------------------------------------------------------

def test_windows_modifier_mask_single():
    win32con = type("W", (), {
        "MOD_ALT": 0x0001,
        "MOD_CONTROL": 0x0002,
        "MOD_SHIFT": 0x0004,
        "MOD_WIN": 0x0008,
    })
    assert _windows_modifier_mask(("shift",), win32con) == 0x0004
    assert _windows_modifier_mask((), win32con) == 0


# ---------------------------------------------------------------------------
# NoopStatusIndicatorProvider
# ---------------------------------------------------------------------------

def test_noop_status_indicator():
    provider = NoopStatusIndicatorProvider()
    assert provider.pid is None
    provider.start()  # should not raise
    provider.stop()   # should not raise


# ---------------------------------------------------------------------------
# SubprocessStatusIndicatorProvider
# ---------------------------------------------------------------------------

def test_subprocess_status_indicator_constructor():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    assert provider.host == "localhost"
    assert provider.port == 7878
    assert provider._process is None


def test_subprocess_status_indicator_pid_before_start():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    assert provider.pid is None


def test_subprocess_status_indicator_start_darwin():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    mock_process = MagicMock()
    mock_process.pid = 1234
    mock_process.poll.return_value = None
    with patch("whisper_local.platform.providers.sys.platform", "darwin"), \
         patch("whisper_local.platform.providers.subprocess.Popen", return_value=mock_process):
        provider.start()
    assert provider.pid == 1234


def test_subprocess_status_indicator_start_idempotent():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    provider._process = mock_process
    with patch("whisper_local.platform.providers.sys.platform", "darwin"), \
         patch("whisper_local.platform.providers.subprocess.Popen") as mock_popen:
        provider.start()
    mock_popen.assert_not_called()


def test_subprocess_status_indicator_stop():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    provider._process = mock_process
    provider.stop()
    mock_process.terminate.assert_called_once()
    assert provider._process is None


def test_subprocess_status_indicator_stop_timeout_kills():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 1.5)
    provider._process = mock_process
    provider.stop()
    mock_process.kill.assert_called_once()
    assert provider._process is None


def test_subprocess_status_indicator_stop_noop():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    provider.stop()  # no process, should not raise


def test_subprocess_status_indicator_stop_already_exited():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    mock_process = MagicMock()
    mock_process.poll.return_value = 0
    provider._process = mock_process
    provider.stop()
    mock_process.terminate.assert_not_called()
    assert provider._process is None


# ---------------------------------------------------------------------------
# NoopPasteProvider / DefaultPasteProvider
# ---------------------------------------------------------------------------

def test_noop_paste_provider():
    assert NoopPasteProvider().paste_from_clipboard() is False


def test_default_paste_provider():
    with patch("whisper_local.output.paste_from_clipboard", return_value=True):
        assert DefaultPasteProvider().paste_from_clipboard() is True


# ---------------------------------------------------------------------------
# X11HotkeyProvider._matches_state
# ---------------------------------------------------------------------------

def test_x11_matches_state_ignores_lock_and_num():
    xlib_x = type("X", (), {
        "LockMask": 2,
        "Mod2Mask": 16,
    })
    # Required: ctrl (4), state has ctrl + CapsLock + NumLock
    assert X11HotkeyProvider._matches_state(4 | 2 | 16, 4, xlib_x) is True
    # Required: ctrl (4), state has only CapsLock
    assert X11HotkeyProvider._matches_state(2, 4, xlib_x) is False


# ---------------------------------------------------------------------------
# Abstract base classes raise NotImplementedError
# ---------------------------------------------------------------------------

def test_hotkey_provider_abstract_start():
    class TestProvider(HotkeyProvider):
        def start(self): return super().start()
        def stop(self): return super().stop()
    p = TestProvider()
    with pytest.raises(NotImplementedError):
        p.start()


def test_hotkey_provider_abstract_stop():
    class TestProvider(HotkeyProvider):
        def start(self): return super().start()
        def stop(self): return super().stop()
    p = TestProvider()
    with pytest.raises(NotImplementedError):
        p.stop()


def test_status_indicator_provider_abstract_pid():
    class TestProvider(StatusIndicatorProvider):
        @property
        def pid(self): return super().pid
        def start(self): return super().start()
        def stop(self): return super().stop()
    p = TestProvider()
    with pytest.raises(NotImplementedError):
        _ = p.pid


def test_status_indicator_provider_abstract_start():
    class TestProvider(StatusIndicatorProvider):
        @property
        def pid(self): return None
        def start(self): return super().start()
        def stop(self): pass
    p = TestProvider()
    with pytest.raises(NotImplementedError):
        p.start()


def test_status_indicator_provider_abstract_stop():
    class TestProvider(StatusIndicatorProvider):
        @property
        def pid(self): return None
        def start(self): pass
        def stop(self): return super().stop()
    p = TestProvider()
    with pytest.raises(NotImplementedError):
        p.stop()


def test_paste_provider_abstract():
    class TestProvider(PasteProvider):
        def paste_from_clipboard(self): return super().paste_from_clipboard()
    p = TestProvider()
    with pytest.raises(NotImplementedError):
        p.paste_from_clipboard()


# ---------------------------------------------------------------------------
# NoopHotkeyProvider no-reason
# ---------------------------------------------------------------------------

def test_noop_hotkey_provider_no_reason():
    provider = NoopHotkeyProvider()
    provider.start()  # should not log
    provider.stop()   # should not raise
