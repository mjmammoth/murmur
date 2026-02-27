from __future__ import annotations

import sys
import types
from unittest.mock import patch

from whisper_local.output import (
    ClipboardSnapshot,
    _clipboard_macos_snapshot,
    _restore_macos_snapshot,
    capture_clipboard_snapshot,
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
        def generalPasteboard():
            """
            Create a FakePasteboard instance for tests that simulates the macOS system pasteboard.

            Returns:
                FakePasteboard: A new FakePasteboard instance.
            """
            return FakePasteboard()

        def pasteboardItems(self):
            """
            Create a list of pasteboard items used by the fake pasteboard.

            Returns:
                list: A list containing a single FakeItem instance representing a pasteboard item.
            """
            return [FakeItem()]

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
        def generalPasteboard():
            """
            Create a FakePasteboard instance for tests that simulates the macOS system pasteboard.

            Returns:
                FakePasteboard: A new FakePasteboard instance.
            """
            return FakePasteboard()

        def pasteboardItems(self):
            """
            Create a list of pasteboard items used by the fake pasteboard.

            Returns:
                list: A list containing a single FakeItem instance representing a pasteboard item.
            """
            return [FakeItem()]

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
        def generalPasteboard():
            """
            Create a FakePasteboard instance for tests that simulates the macOS system pasteboard.

            Returns:
                FakePasteboard: A new FakePasteboard instance.
            """
            return FakePasteboard()

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
        def generalPasteboard():
            """
            Create a FakePasteboard instance for tests that simulates the macOS system pasteboard.

            Returns:
                FakePasteboard: A new FakePasteboard instance.
            """
            return FakePasteboard()

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
