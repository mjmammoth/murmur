from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pyperclip

from whisper_local.output import (
    ClipboardSnapshot,
    _clipboard_macos_snapshot,
    _clipboard_text_snapshot,
    _restore_macos_snapshot,
    append_to_file,
    capture_clipboard_snapshot,
    copy_to_clipboard,
    paste_from_clipboard,
    restore_clipboard_snapshot,
)


def test_capture_clipboard_snapshot_collects_macos_and_text() -> None:
    with patch("whisper_local.output._clipboard_macos_snapshot", return_value=[{"public.text": b"abc"}]), patch(
        "whisper_local.output._clipboard_text_snapshot", return_value="hello"
    ):
        snapshot = capture_clipboard_snapshot()

    assert snapshot.macos_items == [{"public.text": b"abc"}]
    assert snapshot.text == "hello"


def test_restore_clipboard_snapshot_prefers_macos_path() -> None:
    snapshot = ClipboardSnapshot(macos_items=[{"public.text": b"abc"}], text="hello")

    with patch("whisper_local.output._restore_macos_snapshot", return_value=True) as mock_restore_macos, patch(
        "whisper_local.output.pyperclip.copy"
    ) as mock_copy:
        restored = restore_clipboard_snapshot(snapshot)

    assert restored is True
    mock_restore_macos.assert_called_once_with([{"public.text": b"abc"}])
    mock_copy.assert_not_called()


def test_restore_clipboard_snapshot_falls_back_to_text() -> None:
    snapshot = ClipboardSnapshot(macos_items=[{"public.text": b"abc"}], text="hello")

    with patch("whisper_local.output._restore_macos_snapshot", return_value=False), patch(
        "whisper_local.output.pyperclip.copy"
    ) as mock_copy:
        restored = restore_clipboard_snapshot(snapshot)

    assert restored is True
    mock_copy.assert_called_once_with("hello")


def test_clipboard_macos_snapshot_uses_pasteboard_api(monkeypatch) -> None:
    class FakePayload:
        def __bytes__(self):
            """
            Return the object's bytes representation.

            Returns:
                bytes: The bytes value for this instance (b"abc").
            """
            return b"abc"

    class FakeItem:
        def types(self):
            """
            Provide the pasteboard uniform type identifiers this payload supports.

            Returns:
                list[str]: A list with the UTI "public.utf8-plain-text".
            """
            return ["public.utf8-plain-text"]

        def dataForType_(self, _item_type):
            """
            Return a fake payload object for a requested pasteboard data type.

            Parameters:
                _item_type (str): Pasteboard type identifier (ignored by this fake).

            Returns:
                FakePayload: A new FakePayload instance representing the data for the requested type.
            """
            return FakePayload()

    class FakePasteboard:
        @staticmethod
        def general_pasteboard():
            """
            Create a FakePasteboard instance for tests that simulates the macOS system pasteboard.

            Returns:
                FakePasteboard: A new FakePasteboard instance.
            """
            return FakePasteboard()

        def pasteboard_items(self):
            """
            Create a list of pasteboard items used by the fake pasteboard.

            Returns:
                list: A list containing a single FakeItem instance representing a pasteboard item.
            """
            return [FakeItem()]

        generalPasteboard = staticmethod(general_pasteboard)
        pasteboardItems = pasteboard_items

    fake_appkit = types.SimpleNamespace(NSPasteboard=FakePasteboard)
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setattr("whisper_local.output.sys.platform", "darwin")

    snapshot = _clipboard_macos_snapshot()

    assert snapshot == [{"public.utf8-plain-text": b"abc"}]


def test_clipboard_macos_snapshot_skips_empty_items(monkeypatch) -> None:
    class FakeItem:
        def types(self):
            """
            Provide the pasteboard uniform type identifiers this payload supports.

            Returns:
                list[str]: A list with the UTI "public.utf8-plain-text".
            """
            return ["public.utf8-plain-text"]

        def dataForType_(self, _item_type):
            """
            Simulate retrieving data for a pasteboard item; always indicates no data available.

            Parameters:
                _item_type: The requested pasteboard data type (ignored).

            Returns:
                None to indicate the item has no data for the requested type.
            """
            return None

    class FakePasteboard:
        @staticmethod
        def general_pasteboard():
            """
            Create a FakePasteboard instance for tests that simulates the macOS system pasteboard.

            Returns:
                FakePasteboard: A new FakePasteboard instance.
            """
            return FakePasteboard()

        def pasteboard_items(self):
            """
            Create a list of pasteboard items used by the fake pasteboard.

            Returns:
                list: A list containing a single FakeItem instance representing a pasteboard item.
            """
            return [FakeItem()]

        generalPasteboard = staticmethod(general_pasteboard)
        pasteboardItems = pasteboard_items

    fake_appkit = types.SimpleNamespace(NSPasteboard=FakePasteboard)
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setattr("whisper_local.output.sys.platform", "darwin")

    snapshot = _clipboard_macos_snapshot()

    assert snapshot == []


def test_restore_macos_snapshot_writes_all_items(monkeypatch) -> None:
    written_objects: list[object] = []

    class FakeNSData:
        @staticmethod
        def dataWithBytes_length_(payload, _length):
            """
            Provide the payload unchanged for compatibility with an Objective-C-style dataWithBytes:length: call.

            Parameters:
            	payload: The data-like object to return. May be bytes, bytearray, or any object representing raw data.
            	_length: Ignored; present for API compatibility with calls that supply a length.

            Returns:
            	The original `payload` object unchanged.
            """
            return payload

    class FakePasteboardItem:
        @classmethod
        def alloc(cls):
            """
            Create a new instance of the class.

            Returns:
                instance: A new instance of the class.
            """
            return cls()

        def init(self):
            """
            Initialize the instance by creating an empty values mapping.

            Sets self.values to an empty dictionary.

            Returns:
                self: The same instance.
            """
            self.values = {}
            return self

        def setData_forType_(self, payload, item_type):
            """
            Store the given payload under the specified pasteboard type key in this item's values.

            Parameters:
                payload (bytes): The data to associate with the pasteboard type.
                item_type (str): The pasteboard/type identifier used as the dictionary key.
            """
            self.values[item_type] = payload

    class FakePasteboard:
        @staticmethod
        def general_pasteboard():
            """
            Create a FakePasteboard instance for tests that simulates the macOS system pasteboard.

            Returns:
                FakePasteboard: A new FakePasteboard instance.
            """
            return FakePasteboard()

        generalPasteboard = staticmethod(general_pasteboard)

        def clearContents(self):
            """
            Clear all contents of the receiver.
            """
            return None

        def writeObjects_(self, objects):
            """
            Append the given pasteboard objects to the captured write list.

            Parameters:
                objects (iterable): Sequence of objects to write to the pasteboard; each object is recorded into the test's captured written_objects list.

            Returns:
                bool: True if the write is considered successful.
            """
            written_objects.extend(objects)
            return True

    fake_appkit = types.SimpleNamespace(
        NSPasteboard=FakePasteboard,
        NSPasteboardItem=FakePasteboardItem,
    )
    fake_foundation = types.SimpleNamespace(NSData=FakeNSData)

    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)
    monkeypatch.setattr("whisper_local.output.sys.platform", "darwin")

    restored = _restore_macos_snapshot([{"public.utf8-plain-text": b"hello"}])

    assert restored is True
    assert len(written_objects) == 1
    assert written_objects[0].values == {"public.utf8-plain-text": b"hello"}


def test_restore_macos_snapshot_returns_false_when_write_fails(monkeypatch) -> None:
    class FakeNSData:
        @staticmethod
        def dataWithBytes_length_(payload, _length):
            """
            Provide the payload unchanged for compatibility with an Objective-C-style dataWithBytes:length: call.

            Parameters:
            	payload: The data-like object to return. May be bytes, bytearray, or any object representing raw data.
            	_length: Ignored; present for API compatibility with calls that supply a length.

            Returns:
            	The original `payload` object unchanged.
            """
            return payload

    class FakePasteboardItem:
        @classmethod
        def alloc(cls):
            """
            Create a new instance of the class.

            Returns:
                instance: A new instance of the class.
            """
            return cls()

        def init(self):
            """
            Initialize the instance by creating an empty values mapping.

            Sets self.values to an empty dictionary.

            Returns:
                self: The same instance.
            """
            self.values = {}
            return self

        def setData_forType_(self, payload, item_type):
            """
            Store the given payload under the specified pasteboard type key in this item's values.

            Parameters:
                payload (bytes): The data to associate with the pasteboard type.
                item_type (str): The pasteboard/type identifier used as the dictionary key.
            """
            self.values[item_type] = payload

    class FakePasteboard:
        @staticmethod
        def general_pasteboard():
            """
            Create a FakePasteboard instance for tests that simulates the macOS system pasteboard.

            Returns:
                FakePasteboard: A new FakePasteboard instance.
            """
            return FakePasteboard()

        generalPasteboard = staticmethod(general_pasteboard)

        def clearContents(self):
            """
            Clear all contents of the receiver.
            """
            return None

        def writeObjects_(self, _objects):
            """
            Simulate writing objects to a pasteboard and indicate the write failed.

            Parameters:
                _objects (list): The objects intended to be written to the pasteboard.

            Returns:
                False: Indicates the write operation failed.
            """
            return False

    fake_appkit = types.SimpleNamespace(
        NSPasteboard=FakePasteboard,
        NSPasteboardItem=FakePasteboardItem,
    )
    fake_foundation = types.SimpleNamespace(NSData=FakeNSData)

    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)
    monkeypatch.setattr("whisper_local.output.sys.platform", "darwin")

    restored = _restore_macos_snapshot([{"public.utf8-plain-text": b"hello"}])

    assert restored is False


# ---------------------------------------------------------------------------
# _clipboard_text_snapshot
# ---------------------------------------------------------------------------

def test_clipboard_text_snapshot_success():
    with patch("whisper_local.output.pyperclip.paste", return_value="hello"):
        assert _clipboard_text_snapshot() == "hello"


def test_clipboard_text_snapshot_exception():
    with patch("whisper_local.output.pyperclip.paste", side_effect=pyperclip.PyperclipException("fail")):
        assert _clipboard_text_snapshot() is None


# ---------------------------------------------------------------------------
# copy_to_clipboard
# ---------------------------------------------------------------------------

def test_copy_to_clipboard_success():
    with patch("whisper_local.output.pyperclip.copy") as mock_copy:
        assert copy_to_clipboard("test") is True
    mock_copy.assert_called_once_with("test")


def test_copy_to_clipboard_failure():
    with patch("whisper_local.output.pyperclip.copy", side_effect=pyperclip.PyperclipException("fail")):
        assert copy_to_clipboard("test") is False


# ---------------------------------------------------------------------------
# paste_from_clipboard
# ---------------------------------------------------------------------------

def test_paste_from_clipboard_non_darwin():
    with patch("whisper_local.output.sys.platform", "linux"):
        assert paste_from_clipboard() is False


def test_paste_from_clipboard_darwin_success():
    with patch("whisper_local.output.sys.platform", "darwin"), \
         patch("whisper_local.output.subprocess.run"):
        assert paste_from_clipboard() is True


def test_paste_from_clipboard_file_not_found():
    with patch("whisper_local.output.sys.platform", "darwin"), \
         patch("whisper_local.output.subprocess.run", side_effect=FileNotFoundError):
        assert paste_from_clipboard() is False


def test_paste_from_clipboard_called_process_error_permission():
    exc = subprocess.CalledProcessError(1, "osascript", stderr="not permitted")
    with patch("whisper_local.output.sys.platform", "darwin"), \
         patch("whisper_local.output.subprocess.run", side_effect=exc):
        assert paste_from_clipboard() is False


def test_paste_from_clipboard_called_process_error_other():
    exc = subprocess.CalledProcessError(1, "osascript", stderr="some error")
    with patch("whisper_local.output.sys.platform", "darwin"), \
         patch("whisper_local.output.subprocess.run", side_effect=exc):
        assert paste_from_clipboard() is False


def test_paste_from_clipboard_oserror_permission():
    with patch("whisper_local.output.sys.platform", "darwin"), \
         patch("whisper_local.output.subprocess.run", side_effect=OSError("not permitted")):
        assert paste_from_clipboard() is False


def test_paste_from_clipboard_oserror_other():
    with patch("whisper_local.output.sys.platform", "darwin"), \
         patch("whisper_local.output.subprocess.run", side_effect=OSError("random error")):
        assert paste_from_clipboard() is False


# ---------------------------------------------------------------------------
# append_to_file
# ---------------------------------------------------------------------------

def test_append_to_file_creates_dirs_and_writes(tmp_path: Path):
    target = tmp_path / "sub" / "output.txt"
    append_to_file(target, "hello world")
    assert target.read_text(encoding="utf-8") == "hello world\n"


def test_append_to_file_appends_newline_when_missing(tmp_path: Path):
    target = tmp_path / "output.txt"
    append_to_file(target, "line1")
    append_to_file(target, "line2\n")
    content = target.read_text(encoding="utf-8")
    assert content == "line1\nline2\n"


# ---------------------------------------------------------------------------
# restore_clipboard_snapshot — edge cases
# ---------------------------------------------------------------------------

def test_restore_clipboard_snapshot_none():
    assert restore_clipboard_snapshot(None) is False


def test_restore_clipboard_snapshot_text_pyperclip_failure():
    snapshot = ClipboardSnapshot(macos_items=None, text="hello")
    with patch("whisper_local.output.pyperclip.copy", side_effect=pyperclip.PyperclipException("fail")):
        assert restore_clipboard_snapshot(snapshot) is False


def test_restore_clipboard_snapshot_no_text_no_macos():
    snapshot = ClipboardSnapshot(macos_items=None, text=None)
    assert restore_clipboard_snapshot(snapshot) is False


# ---------------------------------------------------------------------------
# _clipboard_macos_snapshot — non-darwin / AppKit unavailable
# ---------------------------------------------------------------------------

def test_clipboard_macos_snapshot_non_darwin():
    with patch("whisper_local.output.sys.platform", "linux"):
        assert _clipboard_macos_snapshot() is None


def test_clipboard_macos_snapshot_appkit_import_error(monkeypatch):
    monkeypatch.setattr("whisper_local.output.sys.platform", "darwin")
    # Remove AppKit from modules so the import fails
    with patch.dict("sys.modules", {"AppKit": None}):
        assert _clipboard_macos_snapshot() is None


# ---------------------------------------------------------------------------
# _clipboard_macos_snapshot — pasteboard has no items
# ---------------------------------------------------------------------------

def test_clipboard_macos_snapshot_empty_pasteboard(monkeypatch):
    class FakePasteboard:
        @staticmethod
        def general_pasteboard():
            return FakePasteboard()

        def pasteboard_items(self):
            return None

        generalPasteboard = staticmethod(general_pasteboard)
        pasteboardItems = pasteboard_items

    fake_appkit = types.SimpleNamespace(NSPasteboard=FakePasteboard)
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setattr("whisper_local.output.sys.platform", "darwin")
    assert _clipboard_macos_snapshot() == []
