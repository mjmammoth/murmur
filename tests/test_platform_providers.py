from __future__ import annotations

import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from murmur.platform.providers import (
    DefaultPasteProvider,
    HotkeyProvider,
    MacOSHotkeyProvider,
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

    with patch("murmur.platform.providers.logger") as mock_logger:
        provider.start()

    mock_logger.info.assert_called_once()


def test_x11_provider_start_stop_idempotent():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)

    thread = Mock()
    thread.is_alive.return_value = True

    with patch("murmur.platform.providers.threading.Thread", return_value=thread) as mock_thread_ctor:
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
    with patch("murmur.platform.providers.sys.platform", "darwin"), \
         patch("murmur.platform.providers.subprocess.Popen", return_value=mock_process):
        provider.start()
    assert provider.pid == 1234


def test_subprocess_status_indicator_start_idempotent():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    provider._process = mock_process
    with patch("murmur.platform.providers.sys.platform", "darwin"), \
         patch("murmur.platform.providers.subprocess.Popen") as mock_popen:
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
    with patch("murmur.output.paste_from_clipboard", return_value=True):
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


def _install_fake_xlib(
    monkeypatch: pytest.MonkeyPatch,
    *,
    keysym: int = 44,
    keycode: int = 77,
) -> tuple[Mock, Mock, ModuleType]:
    root = Mock()
    display = Mock()
    display.screen.return_value = SimpleNamespace(root=root)
    display.keysym_to_keycode.return_value = keycode

    xlib_x = ModuleType("Xlib.X")
    xlib_x.ShiftMask = 1
    xlib_x.ControlMask = 4
    xlib_x.Mod1Mask = 8
    xlib_x.Mod4Mask = 64
    xlib_x.LockMask = 2
    xlib_x.Mod2Mask = 16
    xlib_x.GrabModeAsync = 1
    xlib_x.KeyPress = 2
    xlib_x.KeyRelease = 3

    xlib_xk = ModuleType("Xlib.XK")
    xlib_xk.string_to_keysym = Mock(return_value=keysym)

    xlib_display = ModuleType("Xlib.display")
    xlib_display.Display = Mock(return_value=display)

    xlib_pkg = ModuleType("Xlib")
    xlib_pkg.X = xlib_x
    xlib_pkg.XK = xlib_xk
    xlib_pkg.display = xlib_display

    monkeypatch.setitem(sys.modules, "Xlib", xlib_pkg)
    monkeypatch.setitem(sys.modules, "Xlib.X", xlib_x)
    monkeypatch.setitem(sys.modules, "Xlib.XK", xlib_xk)
    monkeypatch.setitem(sys.modules, "Xlib.display", xlib_display)

    return display, root, xlib_x


def _install_fake_win32(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, ModuleType, ModuleType]:
    win32api = ModuleType("win32api")
    win32api.GetCurrentThreadId = Mock(return_value=321)
    win32api.PostThreadMessage = Mock()

    win32con = ModuleType("win32con")
    win32con.WM_QUIT = 0x12
    win32con.WM_HOTKEY = 0x312
    win32con.MOD_ALT = 0x0001
    win32con.MOD_CONTROL = 0x0002
    win32con.MOD_SHIFT = 0x0004
    win32con.MOD_WIN = 0x0008
    win32con.VK_CONTROL = 0x11
    win32con.VK_SHIFT = 0x10
    win32con.VK_MENU = 0x12
    win32con.VK_LWIN = 0x5B
    win32con.VK_RWIN = 0x5C

    win32gui = ModuleType("win32gui")
    win32gui.RegisterHotKey = Mock(return_value=True)
    win32gui.GetMessage = Mock()
    win32gui.TranslateMessage = Mock()
    win32gui.DispatchMessage = Mock()
    win32gui.UnregisterHotKey = Mock()

    monkeypatch.setitem(sys.modules, "win32api", win32api)
    monkeypatch.setitem(sys.modules, "win32con", win32con)
    monkeypatch.setitem(sys.modules, "win32gui", win32gui)
    return win32api, win32con, win32gui


def test_macos_hotkey_provider_delegates_to_listener(monkeypatch: pytest.MonkeyPatch):
    listener = Mock()
    hotkey_module = ModuleType("murmur.hotkey")
    hotkey_module.HotkeyListener = Mock(return_value=listener)
    monkeypatch.setitem(sys.modules, "murmur.hotkey", hotkey_module)

    provider = MacOSHotkeyProvider("ctrl+f3", on_press=lambda: None, on_release=lambda: None)
    provider.start()
    provider.stop()

    hotkey_module.HotkeyListener.assert_called_once()
    listener.start.assert_called_once()
    listener.stop.assert_called_once()


def test_x11_provider_stop_ignores_display_close_errors():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    provider._display = Mock(close=Mock(side_effect=RuntimeError("close failed")))
    provider._thread = Mock(is_alive=Mock(return_value=False))

    provider.stop()

    assert provider._thread is None
    assert provider._pressed is False


def test_x11_setup_grab_success(monkeypatch: pytest.MonkeyPatch):
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    display, root, xlib_x = _install_fake_xlib(monkeypatch, keysym=11, keycode=33)

    out_display, out_root, out_keycode, modifier_mask, grab_masks, out_xlib_x = provider._setup_grab()

    assert out_display is display
    assert out_root is root
    assert out_keycode == 33
    assert modifier_mask == 4
    assert grab_masks == (0, xlib_x.LockMask, xlib_x.Mod2Mask, xlib_x.LockMask | xlib_x.Mod2Mask)
    assert out_xlib_x is xlib_x
    assert root.grab_key.call_count == 4
    display.flush.assert_called_once()


def test_x11_setup_grab_rejects_unsupported_keysym(monkeypatch: pytest.MonkeyPatch):
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    _install_fake_xlib(monkeypatch, keysym=0, keycode=33)

    with pytest.raises(RuntimeError, match="Unsupported X11 hotkey key"):
        provider._setup_grab()


def test_x11_setup_grab_rejects_bad_keycode(monkeypatch: pytest.MonkeyPatch):
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    _install_fake_xlib(monkeypatch, keysym=11, keycode=0)

    with pytest.raises(RuntimeError, match="Failed to resolve X11 keycode"):
        provider._setup_grab()


def test_x11_poll_next_event_returns_event_when_available():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    display = Mock()
    event = object()
    display.pending_events.return_value = 1
    display.next_event.return_value = event

    assert provider._poll_next_event(display) is event


def test_x11_poll_next_event_waits_then_none_when_still_empty():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    display = Mock()
    display.pending_events.side_effect = [0, 0]

    with patch("murmur.platform.providers.select.select", return_value=([], [], [])) as select_mock:
        assert provider._poll_next_event(display) is None

    select_mock.assert_called_once()


def test_x11_poll_next_event_returns_none_when_stop_requested():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    display = Mock()
    display.pending_events.return_value = 0
    provider._stop_event.set()

    with patch("murmur.platform.providers.select.select", return_value=([], [], [])):
        assert provider._poll_next_event(display) is None


def test_x11_poll_next_event_returns_none_on_exception():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    display = Mock()
    display.pending_events.side_effect = RuntimeError("boom")

    assert provider._poll_next_event(display) is None


def test_x11_handle_event_triggers_press_once_then_release():
    on_press = Mock()
    on_release = Mock()
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=on_press, on_release=on_release)
    xlib_x = type("X", (), {"KeyPress": 2, "KeyRelease": 3, "LockMask": 2, "Mod2Mask": 16})
    press_event = SimpleNamespace(type=2, detail=77, state=4)
    release_event = SimpleNamespace(type=3, detail=77, state=4)

    provider._handle_event(press_event, keycode=77, modifier_mask=4, xlib_x=xlib_x)
    provider._handle_event(press_event, keycode=77, modifier_mask=4, xlib_x=xlib_x)
    provider._handle_event(release_event, keycode=77, modifier_mask=4, xlib_x=xlib_x)

    on_press.assert_called_once()
    on_release.assert_called_once()
    assert provider._pressed is False


def test_x11_handle_event_releases_when_modifier_state_changes():
    on_release = Mock()
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=on_release)
    xlib_x = type("X", (), {"KeyPress": 2, "KeyRelease": 3, "LockMask": 2, "Mod2Mask": 16})
    provider._pressed = True
    release_event = SimpleNamespace(type=3, detail=999, state=0)

    provider._handle_event(release_event, keycode=77, modifier_mask=4, xlib_x=xlib_x)

    on_release.assert_called_once()
    assert provider._pressed is False


def test_x11_cleanup_grab_ungrabs_and_closes():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    root = Mock()
    display = Mock()
    provider._display = display

    provider._cleanup_grab(display, root, keycode=77, modifier_mask=4, grab_masks=(0, 2))

    root.ungrab_key.assert_has_calls([call(77, 4), call(77, 6)])
    display.flush.assert_called_once()
    display.close.assert_called_once()
    assert provider._display is None


def test_x11_cleanup_grab_tolerates_ungrab_errors():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    root = Mock(ungrab_key=Mock(side_effect=RuntimeError("cannot ungrab")))
    display = Mock()

    provider._cleanup_grab(display, root, keycode=77, modifier_mask=4, grab_masks=(0, 2))

    display.close.assert_called_once()
    assert provider._display is None


def test_x11_cleanup_grab_tolerates_display_close_errors():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    root = Mock()
    display = Mock(close=Mock(side_effect=RuntimeError("close failed")))

    provider._cleanup_grab(display, root, keycode=77, modifier_mask=4, grab_masks=(0, 2))

    root.ungrab_key.assert_has_calls([call(77, 4), call(77, 6)])
    assert provider._display is None


def test_x11_run_handles_events_and_cleans_up():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    provider._stop_event.clear()
    display = object()
    root = object()
    xlib_x = object()
    event = object()

    def _poll(_display):
        provider._stop_event.set()
        return event

    with patch.object(provider, "_setup_grab", return_value=(display, root, 12, 4, (0,), xlib_x)), \
         patch.object(provider, "_poll_next_event", side_effect=_poll), \
         patch.object(provider, "_handle_event") as handle_mock, \
         patch.object(provider, "_cleanup_grab") as cleanup_mock:
        provider._run()

    handle_mock.assert_called_once_with(event, 12, 4, xlib_x)
    cleanup_mock.assert_called_once_with(display, root, 12, 4, (0,))


def test_x11_run_logs_and_cleans_up_on_setup_error():
    provider = X11HotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)

    with patch.object(provider, "_setup_grab", side_effect=RuntimeError("boom")), \
         patch.object(provider, "_cleanup_grab") as cleanup_mock, \
         patch("murmur.platform.providers.logger") as logger_mock:
        provider._run()

    logger_mock.error.assert_called_once()
    cleanup_mock.assert_called_once_with(None, None, 0, 0, ())


def test_windows_provider_start_is_idempotent():
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    thread = Mock()
    thread.is_alive.return_value = True

    with patch("murmur.platform.providers.threading.Thread", return_value=thread) as thread_ctor:
        provider.start()
        provider.start()

    thread_ctor.assert_called_once()
    thread.start.assert_called_once()


def test_windows_provider_stop_posts_quit_and_joins(monkeypatch: pytest.MonkeyPatch):
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    thread = Mock()
    thread.is_alive.return_value = True
    provider._thread = thread
    provider._thread_id = 99
    provider._pressed = True
    win32api, win32con, _ = _install_fake_win32(monkeypatch)

    provider.stop()

    win32api.PostThreadMessage.assert_called_once_with(99, win32con.WM_QUIT, 0, 0)
    thread.join.assert_called_once_with(timeout=1.5)
    assert provider._thread is None
    assert provider._thread_id is None
    assert provider._pressed is False


def test_windows_provider_stop_tolerates_import_errors():
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    thread = Mock()
    thread.is_alive.return_value = True
    provider._thread = thread
    provider._thread_id = 99

    with patch.dict(sys.modules, {"win32api": None, "win32con": None}):
        provider.stop()

    thread.join.assert_called_once_with(timeout=1.5)
    assert provider._thread is None
    assert provider._thread_id is None
    assert provider._pressed is False


def test_windows_run_processes_hotkey_and_unregisters(monkeypatch: pytest.MonkeyPatch):
    on_press = Mock()
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=on_press, on_release=lambda: None)
    win32api, win32con, win32gui = _install_fake_win32(monkeypatch)
    hotkey_msg = (0, win32con.WM_HOTKEY, provider._hotkey_id, 0, 0, 0)
    quit_msg = (0, win32con.WM_QUIT, 0, 0, 0, 0)
    win32gui.GetMessage.side_effect = [hotkey_msg, quit_msg]
    win32gui.DispatchMessage.side_effect = RuntimeError("dispatch failure")

    with patch.object(provider, "_start_release_monitor") as start_monitor:
        provider._run()

    on_press.assert_called_once()
    start_monitor.assert_called_once_with(win32api, win32con)
    win32gui.RegisterHotKey.assert_called_once()
    win32gui.TranslateMessage.assert_called_once_with(hotkey_msg)
    win32gui.UnregisterHotKey.assert_called_once_with(None, provider._hotkey_id)


def test_windows_run_logs_when_register_hotkey_fails(monkeypatch: pytest.MonkeyPatch):
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    _, _, win32gui = _install_fake_win32(monkeypatch)
    win32gui.RegisterHotKey.return_value = False

    with patch("murmur.platform.providers.logger") as logger_mock:
        provider._run()

    logger_mock.error.assert_called_once()
    win32gui.UnregisterHotKey.assert_not_called()


def test_windows_run_handles_getmessage_exceptions(monkeypatch: pytest.MonkeyPatch):
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    _, _, win32gui = _install_fake_win32(monkeypatch)
    calls = {"count": 0}

    def _raise_then_stop(*_args):
        calls["count"] += 1
        if calls["count"] == 2:
            provider._stop_event.set()
        raise RuntimeError("message failure")

    win32gui.GetMessage.side_effect = _raise_then_stop
    provider._stop_event.clear()
    provider._run()

    # One call continues, second call breaks after stop is set.
    assert calls["count"] == 2
    win32gui.UnregisterHotKey.assert_called_once_with(None, provider._hotkey_id)


def test_windows_run_tolerates_unregister_errors(monkeypatch: pytest.MonkeyPatch):
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    _, win32con, win32gui = _install_fake_win32(monkeypatch)
    win32gui.GetMessage.side_effect = [(0, win32con.WM_QUIT, 0, 0, 0, 0)]
    win32gui.UnregisterHotKey.side_effect = RuntimeError("cannot unregister")

    provider._run()

    win32gui.RegisterHotKey.assert_called_once()
    win32gui.UnregisterHotKey.assert_called_once_with(None, provider._hotkey_id)


def test_windows_start_release_monitor_skips_when_thread_alive():
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    provider._release_monitor_thread = Mock(is_alive=Mock(return_value=True))

    with patch("murmur.platform.providers.threading.Thread") as thread_ctor:
        provider._start_release_monitor(Mock(), Mock())

    thread_ctor.assert_not_called()


def test_windows_start_release_monitor_starts_thread():
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    thread = Mock()

    with patch("murmur.platform.providers.threading.Thread", return_value=thread) as thread_ctor:
        win32api = Mock()
        win32con = Mock()
        provider._start_release_monitor(win32api, win32con)

    thread_ctor.assert_called_once_with(
        target=provider._monitor_release,
        args=(win32api, win32con),
        daemon=True,
    )
    thread.start.assert_called_once()


def test_windows_monitor_release_calls_on_release_when_key_is_up():
    on_release = Mock()
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=on_release)
    provider._pressed = True

    with patch.object(provider, "_is_hotkey_down", return_value=False):
        provider._monitor_release(Mock(), Mock())

    on_release.assert_called_once()
    assert provider._pressed is False


def test_windows_monitor_release_loops_until_stop_event():
    provider = WindowsHotkeyProvider(key="f3", modifiers=("ctrl",), on_press=lambda: None, on_release=lambda: None)
    provider._pressed = True
    provider._stop_event.clear()

    def _sleep(_seconds: float) -> None:
        provider._stop_event.set()

    with patch.object(provider, "_is_hotkey_down", return_value=True), \
         patch("murmur.platform.providers.time.sleep", side_effect=_sleep):
        provider._monitor_release(Mock(), Mock())


def _win32_key_modules() -> tuple[Mock, type]:
    win32api = Mock()
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
    return win32api, win32con


@pytest.mark.parametrize(
    ("modifiers", "vk_code"),
    [
        (("ctrl",), 0x11),
        (("alt",), 0x12),
        (("shift",), 0x10),
    ],
)
def test_windows_is_hotkey_down_returns_false_when_required_modifier_missing(
    modifiers: tuple[str, ...],
    vk_code: int,
):
    provider = WindowsHotkeyProvider(key="f3", modifiers=modifiers, on_press=lambda: None, on_release=lambda: None)
    win32api, win32con = _win32_key_modules()
    values = {provider._vk_code: 0x8000, vk_code: 0x0000}
    win32api.GetAsyncKeyState.side_effect = lambda vk: values.get(vk, 0x8000)

    assert provider._is_hotkey_down(win32api, win32con) is False


def test_windows_is_hotkey_down_returns_false_when_main_key_is_up():
    provider = WindowsHotkeyProvider(key="f3", modifiers=(), on_press=lambda: None, on_release=lambda: None)
    win32api, win32con = _win32_key_modules()
    win32api.GetAsyncKeyState.side_effect = lambda _vk: 0

    assert provider._is_hotkey_down(win32api, win32con) is False


def test_windows_is_hotkey_down_requires_one_windows_key():
    provider = WindowsHotkeyProvider(key="f3", modifiers=("cmd",), on_press=lambda: None, on_release=lambda: None)
    win32api, win32con = _win32_key_modules()
    values = {provider._vk_code: 0x8000, 0x5B: 0x0000, 0x5C: 0x0000}
    win32api.GetAsyncKeyState.side_effect = lambda vk: values.get(vk, 0x8000)

    assert provider._is_hotkey_down(win32api, win32con) is False


def test_subprocess_status_indicator_stop_ignores_kill_errors():
    provider = SubprocessStatusIndicatorProvider(host="localhost", port=7878)
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.wait.side_effect = [
        subprocess.TimeoutExpired("cmd", 1.5),
        subprocess.TimeoutExpired("cmd", 1.0),
    ]
    mock_process.kill.side_effect = RuntimeError("kill failed")
    provider._process = mock_process

    provider.stop()

    mock_process.kill.assert_called_once()
    assert provider._process is None
