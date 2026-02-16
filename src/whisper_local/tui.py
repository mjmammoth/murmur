from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, ListItem, ListView, Static

from whisper_local.audio import AudioRecorder
from whisper_local.config import AppConfig, default_config_path, load_config, save_config
from whisper_local.hotkey import HotkeyListener
from whisper_local.model_manager import (
    download_model,
    ensure_model_available,
    is_model_installed,
    list_installed_models,
    model_cache_size_bytes,
    set_selected_model,
)
from whisper_local.noise import RNNoiseSuppressor
from whisper_local.output import append_to_file, copy_to_clipboard, paste_from_clipboard
from whisper_local.transcribe import Transcriber
from whisper_local.vad import VadProcessor


logger = logging.getLogger(__name__)
SPINNER_FRAMES = ("|", "/", "-", "\\")


@dataclass
class TranscriptEntry:
    timestamp: str
    text: str


class TranscriptItem(ListItem):
    def __init__(self, entry: TranscriptEntry) -> None:
        self.entry = entry
        super().__init__(Static(f"{entry.timestamp}  {entry.text}"))


class ModelItem(ListItem):
    def __init__(self, name: str, installed: bool) -> None:
        self.name = name
        self.installed = installed
        label = f"{name}  {'installed' if installed else 'available'}"
        super().__init__(Static(label))


class ModelManagerScreen(Screen):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("p", "pull", "Download"),
        ("r", "remove", "Remove"),
        ("d", "set_default", "Select"),
        ("l", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Models", id="models-title"),
            ListView(id="models-list"),
            Static("", id="models-status"),
            id="models-container",
        )

    def on_mount(self) -> None:
        self.refresh_models()

    def refresh_models(self) -> None:
        list_view = self.query_one("#models-list", ListView)
        self._clear_list_view(list_view)
        for model in list_installed_models():
            list_view.append(ModelItem(model.name, model.installed))

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self.refresh_models()

    def action_pull(self) -> None:
        model = self._selected_model()
        if not model:
            return
        self._set_status(f"Downloading {model}...")
        self.run_worker(lambda: self._download_model(model), thread=True)

    def action_remove(self) -> None:
        model = self._selected_model()
        if not model:
            return
        self._set_status(f"Removing {model}...")
        self.run_worker(lambda: self._remove_model(model), thread=True)

    def action_set_default(self) -> None:
        model = self._selected_model()
        if not model:
            return
        try:
            set_selected_model(model)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self._set_status(f"Selected model set to {model}")

    def _selected_model(self) -> Optional[str]:
        list_view = self.query_one("#models-list", ListView)
        item = list_view.get_highlighted() if hasattr(list_view, "get_highlighted") else list_view.highlighted_child
        if isinstance(item, ModelItem):
            return item.name
        return None

    def _download_model(self, model: str) -> None:
        try:
            download_model(model)
            self.call_from_thread(self._set_status, f"Downloaded {model}")
        except Exception as exc:  # pragma: no cover - runtime dependent
            self.call_from_thread(self._set_status, f"Download failed: {exc}")
        self.call_from_thread(self.refresh_models)

    def _remove_model(self, model: str) -> None:
        from whisper_local.model_manager import remove_model

        try:
            remove_model(model)
            self.call_from_thread(self._set_status, f"Removed {model}")
        except Exception as exc:  # pragma: no cover - runtime dependent
            self.call_from_thread(self._set_status, f"Remove failed: {exc}")
        self.call_from_thread(self.refresh_models)

    def _set_status(self, text: str) -> None:
        status = self.query_one("#models-status", Static)
        status.update(text)

    @staticmethod
    def _clear_list_view(list_view: ListView) -> None:
        if hasattr(list_view, "clear"):
            list_view.clear()
            return
        for child in list(list_view.children):
            child.remove()


class WhisperApp(App):
    CSS = """
    #status {
        padding: 1 2;
        background: $panel;
    }
    #history {
        padding: 0 1;
    }
    #models-container {
        padding: 1 2;
    }
    #models-title {
        padding-bottom: 1;
    }
    #models-status {
        padding-top: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "copy_latest", "Copy latest"),
        ("enter", "copy_selected", "Copy selected"),
        ("a", "toggle_auto_copy", "Auto copy"),
        ("p", "toggle_auto_paste", "Auto paste"),
        ("n", "toggle_noise", "Noise"),
        ("v", "toggle_vad", "VAD"),
        ("m", "models", "Models"),
        ("s", "settings", "Settings"),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.recorder = AudioRecorder(sample_rate=config.audio.sample_rate)
        self.noise = RNNoiseSuppressor(enabled=config.audio.noise_suppression.enabled)
        self.vad = VadProcessor(enabled=config.vad.enabled, aggressiveness=config.vad.aggressiveness)
        self.transcriber = Transcriber(
            model_name=config.model.name,
            device=config.model.device,
            compute_type=config.model.compute_type,
            model_path=config.model.path,
        )
        self.hotkey = HotkeyListener(
            config.hotkey.key,
            on_press=self._handle_hotkey_press,
            on_release=self._handle_hotkey_release,
        )
        self._recording = False
        self._auto_copy = bool(config.auto_copy)
        self._auto_paste = bool(config.auto_paste)
        if self._auto_paste and not self._auto_copy:
            self._auto_copy = True
            self.config.auto_copy = True
            save_config(self.config)
            logger.info("Auto paste enabled in config; forcing auto copy on")
        self._entries: list[TranscriptEntry] = []
        self._status_message = "Initializing..."
        self._busy_operation = False
        self._busy_started_at = monotonic()
        self._busy_hint: str | None = None
        self._spinner_index = 0
        self._download_model_name: str | None = None
        self._download_size_checked_at = 0.0
        self._download_size_display = ""
        self._hotkey_started = False

    def compose(self) -> ComposeResult:
        yield Static(id="status")
        yield ListView(id="history")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.2, self._tick_status)
        self._set_busy_status("Initializing startup...")
        self.run_worker(self._load_model, thread=True)

    def on_unmount(self) -> None:
        if self._hotkey_started:
            self.hotkey.stop()
        self.noise.close()

    def action_models(self) -> None:
        self.push_screen(ModelManagerScreen())

    def action_settings(self) -> None:
        config_path = default_config_path()
        self._set_status(f"Edit settings in {config_path}")

    def action_toggle_auto_copy(self) -> None:
        if self._auto_paste and self._auto_copy:
            logger.info("Rejected auto copy disable request because auto paste is enabled")
            self._set_status("Auto copy remains on while auto paste is enabled")
            return
        self._auto_copy = not self._auto_copy
        self.config.auto_copy = self._auto_copy
        save_config(self.config)
        state = "on" if self._auto_copy else "off"
        self._set_status(f"Auto copy {state}")

    def action_toggle_auto_paste(self) -> None:
        self._auto_paste = not self._auto_paste
        self.config.auto_paste = self._auto_paste
        auto_copy_forced = False
        if self._auto_paste and not self._auto_copy:
            self._auto_copy = True
            self.config.auto_copy = True
            auto_copy_forced = True
            logger.info("Auto paste enabled; forcing auto copy on")
        save_config(self.config)
        if auto_copy_forced:
            self._set_status("Auto paste on; auto copy on")
        else:
            state = "on" if self._auto_paste else "off"
            self._set_status(f"Auto paste {state}")

    def action_toggle_noise(self) -> None:
        self.config.audio.noise_suppression.enabled = not self.config.audio.noise_suppression.enabled
        self.noise = RNNoiseSuppressor(enabled=self.config.audio.noise_suppression.enabled)
        save_config(self.config)
        state = "on" if self.config.audio.noise_suppression.enabled else "off"
        self._set_status(f"Noise suppression {state}")

    def action_toggle_vad(self) -> None:
        self.config.vad.enabled = not self.config.vad.enabled
        self.vad = VadProcessor(enabled=self.config.vad.enabled, aggressiveness=self.config.vad.aggressiveness)
        save_config(self.config)
        state = "on" if self.config.vad.enabled else "off"
        self._set_status(f"VAD {state}")

    def action_copy_latest(self) -> None:
        if not self._entries:
            self._set_status("No transcripts yet")
            return
        latest = self._entries[-1]
        if copy_to_clipboard(latest.text):
            self._set_status("Copied latest transcript")
        else:
            self._set_status("Clipboard copy failed")

    def action_copy_selected(self) -> None:
        list_view = self.query_one("#history", ListView)
        item = list_view.get_highlighted() if hasattr(list_view, "get_highlighted") else list_view.highlighted_child
        if isinstance(item, TranscriptItem):
            if copy_to_clipboard(item.entry.text):
                self._set_status("Copied selected transcript")
            else:
                self._set_status("Clipboard copy failed")

    def _handle_hotkey_press(self) -> None:
        self.call_from_thread(self._on_hotkey_press)

    def _handle_hotkey_release(self) -> None:
        self.call_from_thread(self._on_hotkey_release)

    def _on_hotkey_press(self) -> None:
        if self.config.hotkey.mode == "toggle":
            if self._recording:
                self._stop_recording()
            else:
                self._start_recording()
        else:
            self._start_recording()

    def _on_hotkey_release(self) -> None:
        if self.config.hotkey.mode == "ptt":
            self._stop_recording()

    def _start_recording(self) -> None:
        if self._recording:
            return
        self.recorder.start()
        self._recording = True
        self._set_status("Recording...")

    def _stop_recording(self) -> None:
        if not self._recording:
            return
        audio = self.recorder.stop()
        self._recording = False
        self._set_busy_status("Transcribing...")
        self.run_worker(lambda: self._process_audio(audio), thread=True)

    def _process_audio(self, audio) -> None:
        if audio.size == 0:
            self.call_from_thread(self._set_status, "No audio captured")
            return
        noise_result = self.noise.process(audio, self.config.audio.sample_rate)
        audio = noise_result.audio
        if self.config.vad.enabled:
            vad_result = self.vad.trim(audio, self.config.audio.sample_rate)
            audio = vad_result.audio
        try:
            result = self.transcriber.transcribe(
                audio,
                sample_rate=self.config.audio.sample_rate,
                language=self.config.model.language,
            )
        except Exception as exc:  # pragma: no cover - runtime dependent
            self.call_from_thread(self._set_error_status, f"Transcription failed: {exc}")
            return
        self.call_from_thread(self._handle_transcript, result.text)

    def _handle_transcript(self, text: str) -> None:
        if not text:
            self._set_status("No speech detected")
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = TranscriptEntry(timestamp=timestamp, text=text)
        self._entries.append(entry)
        list_view = self.query_one("#history", ListView)
        list_view.append(TranscriptItem(entry))
        list_view.index = len(list_view.children) - 1

        copied_to_clipboard = True
        if self.config.output.clipboard or self._auto_copy or self._auto_paste:
            copied_to_clipboard = copy_to_clipboard(text)
        if self._auto_paste and copied_to_clipboard:
            paste_from_clipboard()
        if self.config.output.file.enabled:
            append_to_file(self.config.output.file.path, text)
        self._set_ready_status("Ready")

    def _load_model(self) -> None:
        try:
            if self.config.model.path:
                self.call_from_thread(self._set_busy_status, "Loading local model...")
            else:
                installed = is_model_installed(self.config.model.name)
                if not installed and not self.config.model.auto_download:
                    self.call_from_thread(
                        self._set_error_status,
                        f"Model {self.config.model.name} is not installed. Run `whisper.local models pull {self.config.model.name}`.",
                    )
                    return
                if self.config.model.auto_download:
                    self.call_from_thread(
                        self._set_busy_status,
                        (
                            f"Model {self.config.model.name} not found locally. Downloading (first run)..."
                            if not installed
                            else f"Verifying local model {self.config.model.name}..."
                        ),
                        "This can take a few minutes on first run.",
                    )
                    self._download_model_name = self.config.model.name
                    self._download_size_checked_at = 0.0
                    self._download_size_display = ""
                    try:
                        model_path = ensure_model_available(self.config.model.name)
                    except Exception as exc:
                        self.call_from_thread(
                            self._set_error_status,
                            "Model download failed. Check your network, then retry or run "
                            f"`whisper.local models pull {self.config.model.name}`. ({exc})",
                        )
                        return
                    finally:
                        self._download_model_name = None
                        self._download_size_display = ""
                    self.transcriber.model_path = str(model_path)
                    self.call_from_thread(self._set_busy_status, "Model files ready. Loading model...")
                else:
                    self.call_from_thread(self._set_busy_status, "Loading model...")

            self.transcriber.load()
            self.call_from_thread(self._set_ready_status, "Ready")
        except Exception as exc:  # pragma: no cover - runtime dependent
            self.call_from_thread(
                self._set_error_status,
                f"Model load failed: {exc}. You can prefetch with `whisper.local models pull {self.config.model.name}`.",
            )

    def _set_ready_status(self, message: str = "Ready") -> None:
        self._busy_operation = False
        self._busy_hint = None
        self._status_message = message
        if not self._hotkey_started:
            self.hotkey.start()
            self._hotkey_started = True
        self._render_status()

    def _set_status(self, message: str) -> None:
        self._busy_operation = False
        self._busy_hint = None
        self._status_message = message
        self._render_status()

    def _set_busy_status(self, message: str, hint: str | None = None) -> None:
        self._busy_operation = True
        self._busy_started_at = monotonic()
        self._status_message = message
        self._busy_hint = hint
        self._render_status()

    def _set_error_status(self, message: str) -> None:
        self._busy_operation = False
        self._busy_hint = None
        self._status_message = f"Error: {message}"
        self._render_status()

    def _tick_status(self) -> None:
        self._spinner_index = (self._spinner_index + 1) % len(SPINNER_FRAMES)
        if self._busy_operation:
            self._render_status()

    def _render_status(self) -> None:
        message = self._status_message
        if self._busy_operation:
            elapsed = int(monotonic() - self._busy_started_at)
            spinner = SPINNER_FRAMES[self._spinner_index]
            message = f"{spinner} {message} ({elapsed}s)"
            if self._busy_hint:
                message = f"{message} {self._busy_hint}"
            if self._download_model_name:
                now = monotonic()
                if now - self._download_size_checked_at >= 1.0:
                    size = model_cache_size_bytes(self._download_model_name)
                    self._download_size_display = (
                        f"Downloaded ~{_format_bytes(size)}" if size > 0 else ""
                    )
                    self._download_size_checked_at = now
                if self._download_size_display:
                    message = f"{message} {self._download_size_display}"
        self._update_status(message)

    def _update_status(self, message: str) -> None:
        status = self.query_one("#status", Static)
        noise_state = "on" if self.config.audio.noise_suppression.enabled else "off"
        if self.config.audio.noise_suppression.enabled and not self.noise.available:
            noise_state = "on (rnnoise missing)"
        vad_state = "on" if self.config.vad.enabled else "off"
        hotkey = f"{self.config.hotkey.key} ({self.config.hotkey.mode})"
        status.update(
            f"{message} | model: {self.config.model.name} | hotkey: {hotkey} "
            f"| noise: {noise_state} | vad: {vad_state}"
        )


def _format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


def run_app(config: AppConfig | None = None) -> None:
    app_config = config or load_config()
    WhisperApp(app_config).run()
