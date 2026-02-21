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
            return b"abc"

    class FakeItem:
        def types(self):
            return ["public.utf8-plain-text"]

        def dataForType_(self, _item_type):
            return FakePayload()

    class FakePasteboard:
        @staticmethod
        def generalPasteboard():
            return FakePasteboard()

        def pasteboardItems(self):
            return [FakeItem()]

    fake_appkit = types.SimpleNamespace(NSPasteboard=FakePasteboard)
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setattr("whisper_local.output.sys.platform", "darwin")

    snapshot = _clipboard_macos_snapshot()

    assert snapshot == [{"public.utf8-plain-text": b"abc"}]


def test_clipboard_macos_snapshot_skips_empty_items(monkeypatch) -> None:
    class FakeItem:
        def types(self):
            return ["public.utf8-plain-text"]

        def dataForType_(self, _item_type):
            return None

    class FakePasteboard:
        @staticmethod
        def generalPasteboard():
            return FakePasteboard()

        def pasteboardItems(self):
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
            return payload

    class FakePasteboardItem:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            self.values = {}
            return self

        def setData_forType_(self, payload, item_type):
            self.values[item_type] = payload

    class FakePasteboard:
        @staticmethod
        def generalPasteboard():
            return FakePasteboard()

        def clearContents(self):
            return None

        def writeObjects_(self, objects):
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
            return payload

    class FakePasteboardItem:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            self.values = {}
            return self

        def setData_forType_(self, payload, item_type):
            self.values[item_type] = payload

    class FakePasteboard:
        @staticmethod
        def generalPasteboard():
            return FakePasteboard()

        def clearContents(self):
            return None

        def writeObjects_(self, _objects):
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
