from __future__ import annotations

import logging
import select
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable


logger = logging.getLogger(__name__)


PressReleaseCallback = Callable[[], None]


class HotkeyProvider(ABC):
    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError


class StatusIndicatorProvider(ABC):
    @property
    @abstractmethod
    def pid(self) -> int | None:
        raise NotImplementedError

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError


class PasteProvider(ABC):
    @abstractmethod
    def paste_from_clipboard(self) -> bool:
        raise NotImplementedError


class NoopHotkeyProvider(HotkeyProvider):
    def __init__(self, reason: str | None = None) -> None:
        self._reason = reason

    def start(self) -> None:
        if self._reason:
            logger.info("Hotkey provider unavailable: %s", self._reason)

    def stop(self) -> None:
        return


class MacOSHotkeyProvider(HotkeyProvider):
    def __init__(self, hotkey: str, on_press: PressReleaseCallback, on_release: PressReleaseCallback) -> None:
        # Import only on macOS paths to keep non-darwin startup safe.
        from murmur.hotkey import HotkeyListener

        self._listener = HotkeyListener(hotkey, on_press=on_press, on_release=on_release)

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()


def _x11_keysym_name(key: str) -> str:
    if key.startswith("f") and key[1:].isdigit():
        return f"F{key[1:]}"
    mapping = {
        "return": "Return",
        "tab": "Tab",
        "escape": "Escape",
        "space": "space",
    }
    return mapping.get(key, key)


def _x11_modifier_mask(modifiers: tuple[str, ...], xlib_x: Any) -> int:
    modifier_map = {
        "shift": xlib_x.ShiftMask,
        "ctrl": xlib_x.ControlMask,
        "alt": xlib_x.Mod1Mask,
        "cmd": xlib_x.Mod4Mask,
    }
    mask = 0
    for modifier in modifiers:
        mask |= int(modifier_map.get(modifier, 0))
    return mask


class X11HotkeyProvider(HotkeyProvider):
    def __init__(
        self,
        *,
        key: str,
        modifiers: tuple[str, ...],
        on_press: PressReleaseCallback,
        on_release: PressReleaseCallback,
    ) -> None:
        self._key = key
        self._modifiers = modifiers
        self._on_press = on_press
        self._on_release = on_release
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pressed = False
        self._display = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        display = self._display
        if display is not None:
            try:
                display.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        self._pressed = False

    def _setup_grab(self) -> tuple[Any, Any, int, int, tuple[int, ...], Any]:
        from Xlib import X as xlib_x
        from Xlib import XK
        from Xlib import display as xlib_display

        display = xlib_display.Display()
        self._display = display
        root = display.screen().root

        keysym = XK.string_to_keysym(_x11_keysym_name(self._key))
        if not keysym:
            raise RuntimeError(f"Unsupported X11 hotkey key: {self._key}")

        keycode = int(display.keysym_to_keycode(keysym))
        if keycode <= 0:
            raise RuntimeError(f"Failed to resolve X11 keycode for: {self._key}")

        modifier_mask = _x11_modifier_mask(self._modifiers, xlib_x)
        grab_masks = (
            0,
            int(xlib_x.LockMask),
            int(xlib_x.Mod2Mask),
            int(xlib_x.LockMask | xlib_x.Mod2Mask),
        )
        for extra_mask in grab_masks:
            root.grab_key(
                keycode,
                int(modifier_mask | extra_mask),
                False,
                xlib_x.GrabModeAsync,
                xlib_x.GrabModeAsync,
            )
        display.flush()
        return display, root, keycode, modifier_mask, grab_masks, xlib_x

    def _poll_next_event(self, display: Any) -> Any | None:
        try:
            if display.pending_events() == 0:
                select.select([display.fileno()], [], [], 0.15)
                if self._stop_event.is_set():
                    return None
                if display.pending_events() == 0:
                    return None
            return display.next_event()
        except Exception:
            return None

    def _handle_event(self, event: Any, keycode: int, modifier_mask: int, xlib_x: Any) -> None:
        event_type = int(getattr(event, "type", -1))
        detail = int(getattr(event, "detail", -1))
        state = int(getattr(event, "state", 0))

        if event_type == int(xlib_x.KeyPress):
            if detail == keycode and self._matches_state(state, modifier_mask, xlib_x) and not self._pressed:
                self._pressed = True
                self._on_press()
            return

        if event_type == int(xlib_x.KeyRelease) and self._pressed:
            if detail == keycode or (modifier_mask and not self._matches_state(state, modifier_mask, xlib_x)):
                self._pressed = False
                self._on_release()

    def _cleanup_grab(
        self, display: Any | None, root: Any | None, keycode: int, modifier_mask: int, grab_masks: tuple[int, ...],
    ) -> None:
        self._pressed = False
        if display is not None and root is not None and keycode > 0:
            try:
                for extra_mask in grab_masks:
                    root.ungrab_key(keycode, int(modifier_mask | extra_mask))
                display.flush()
            except Exception:
                pass
        if display is not None:
            try:
                display.close()
            except Exception:
                pass
        self._display = None

    def _run(self) -> None:
        display = None
        root = None
        keycode = 0
        modifier_mask = 0
        grab_masks: tuple[int, ...] = tuple()
        try:
            display, root, keycode, modifier_mask, grab_masks, xlib_x = self._setup_grab()

            while not self._stop_event.is_set():
                event = self._poll_next_event(display)
                if event is not None:
                    self._handle_event(event, keycode, modifier_mask, xlib_x)
        except Exception as exc:
            logger.error("Failed to start X11 hotkey provider: %s", exc)
        finally:
            self._cleanup_grab(display, root, keycode, modifier_mask, grab_masks)

    @staticmethod
    def _matches_state(state: int, required_mask: int, xlib_x: Any) -> bool:
        ignored = int(xlib_x.LockMask | xlib_x.Mod2Mask)
        normalized_state = int(state & ~ignored)
        normalized_required = int(required_mask & ~ignored)
        return (normalized_state & normalized_required) == normalized_required


_WINDOWS_FKEY_MAP: dict[str, int] = {
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}


def _windows_vk_code(key: str) -> int:
    if len(key) == 1:
        return ord(key.upper())
    if key in _WINDOWS_FKEY_MAP:
        return _WINDOWS_FKEY_MAP[key]
    special = {
        "space": 0x20,
        "return": 0x0D,
        "tab": 0x09,
        "escape": 0x1B,
    }
    if key in special:
        return special[key]
    raise ValueError(f"Unsupported Windows hotkey key: {key}")


def _windows_modifier_mask(modifiers: tuple[str, ...], win32con: Any) -> int:
    modifier_map = {
        "alt": int(win32con.MOD_ALT),
        "ctrl": int(win32con.MOD_CONTROL),
        "shift": int(win32con.MOD_SHIFT),
        "cmd": int(win32con.MOD_WIN),
    }
    mask = 0
    for modifier in modifiers:
        mask |= int(modifier_map.get(modifier, 0))
    return mask


class WindowsHotkeyProvider(HotkeyProvider):
    def __init__(
        self,
        *,
        key: str,
        modifiers: tuple[str, ...],
        on_press: PressReleaseCallback,
        on_release: PressReleaseCallback,
    ) -> None:
        self._key = key
        self._modifiers = modifiers
        self._on_press = on_press
        self._on_release = on_release
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._release_monitor_thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hotkey_id = 0x5750  # 'WP'
        self._vk_code = _windows_vk_code(self._key)
        self._pressed = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            import win32api
            import win32con

            thread_id = self._thread_id
            if thread_id is not None:
                win32api.PostThreadMessage(thread_id, win32con.WM_QUIT, 0, 0)
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        self._thread_id = None
        self._pressed = False

    def _run(self) -> None:
        registered = False
        try:
            import win32api
            import win32con
            import win32gui

            modifier_mask = _windows_modifier_mask(self._modifiers, win32con)
            self._thread_id = int(win32api.GetCurrentThreadId())
            registered = bool(
                win32gui.RegisterHotKey(
                    None,
                    self._hotkey_id,
                    modifier_mask,
                    self._vk_code,
                )
            )
            if not registered:
                raise RuntimeError("RegisterHotKey returned false")

            while not self._stop_event.is_set():
                try:
                    msg = win32gui.GetMessage(None, 0, 0)
                except Exception:
                    if self._stop_event.is_set():
                        break
                    continue

                message = int(msg[1])
                wparam = int(msg[2])
                if message == int(win32con.WM_QUIT):
                    break

                if message == int(win32con.WM_HOTKEY) and wparam == self._hotkey_id:
                    if not self._pressed:
                        self._pressed = True
                        self._on_press()
                    self._start_release_monitor(win32api, win32con)

                try:
                    win32gui.TranslateMessage(msg)
                    win32gui.DispatchMessage(msg)
                except Exception:
                    # Keep message loop alive; callbacks have already been handled.
                    pass
        except Exception as exc:
            logger.error("Failed to start Windows hotkey provider: %s", exc)
        finally:
            self._pressed = False
            if registered:
                try:
                    import win32gui

                    win32gui.UnregisterHotKey(None, self._hotkey_id)
                except Exception:
                    pass

    def _start_release_monitor(self, win32api: Any, win32con: Any) -> None:
        thread = self._release_monitor_thread
        if thread and thread.is_alive():
            return
        self._release_monitor_thread = threading.Thread(
            target=self._monitor_release,
            args=(win32api, win32con),
            daemon=True,
        )
        self._release_monitor_thread.start()

    def _monitor_release(self, win32api: Any, win32con: Any) -> None:
        while not self._stop_event.is_set() and self._pressed:
            if not self._is_hotkey_down(win32api, win32con):
                self._pressed = False
                self._on_release()
                return
            time.sleep(0.01)

    def _is_hotkey_down(self, win32api: Any, win32con: Any) -> bool:
        def _is_vk_down(vk_code: int) -> bool:
            return bool(int(win32api.GetAsyncKeyState(vk_code)) & 0x8000)

        if not _is_vk_down(self._vk_code):
            return False

        for modifier in self._modifiers:
            if modifier == "ctrl" and not _is_vk_down(int(win32con.VK_CONTROL)):
                return False
            if modifier == "alt" and not _is_vk_down(int(win32con.VK_MENU)):
                return False
            if modifier == "shift" and not _is_vk_down(int(win32con.VK_SHIFT)):
                return False
            if modifier == "cmd":
                left_down = _is_vk_down(int(win32con.VK_LWIN))
                right_down = _is_vk_down(int(win32con.VK_RWIN))
                if not (left_down or right_down):
                    return False
        return True


class NoopStatusIndicatorProvider(StatusIndicatorProvider):
    @property
    def pid(self) -> int | None:
        return None

    def start(self) -> None:
        return

    def stop(self) -> None:
        return


class SubprocessStatusIndicatorProvider(StatusIndicatorProvider):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        python_executable: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.python_executable = python_executable or sys.executable
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def pid(self) -> int | None:
        if self._process is None:
            return None
        return self._process.pid

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._process = subprocess.Popen(
            [
                self.python_executable,
                "-m",
                "murmur.status_indicator",
                "--host",
                self.host,
                "--port",
                str(self.port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is not None:
                return
            process.terminate()
            try:
                process.wait(timeout=1.5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
                try:
                    process.wait(timeout=1.0)
                except Exception:
                    pass
        finally:
            self._process = None


class NoopPasteProvider(PasteProvider):
    def paste_from_clipboard(self) -> bool:
        return False


class DefaultPasteProvider(PasteProvider):
    def paste_from_clipboard(self) -> bool:
        from murmur.output import paste_from_clipboard

        return paste_from_clipboard()
