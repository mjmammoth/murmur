"""WebSocket bridge server for TypeScript TUI communication."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from time import monotonic
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

from whisper_local.audio import AudioRecorder
from whisper_local.config import AppConfig, default_config_path, load_config, save_config
from whisper_local.hotkey import HotkeyListener, parse_hotkey
from whisper_local.model_manager import (
    ModelInfo,
    download_model,
    ensure_model_available,
    is_model_installed,
    list_installed_models,
    remove_model,
    set_default_model,
)
from whisper_local.noise import RNNoiseSuppressor
from whisper_local.output import append_to_file, copy_to_clipboard
from whisper_local.transcribe import Transcriber
from whisper_local.vad import VadProcessor

logger = logging.getLogger(__name__)


class WebSocketLogHandler(logging.Handler):
    """Routes Python log records to connected WebSocket clients."""

    def __init__(self, bridge: "BridgeServer") -> None:
        super().__init__()
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not self.bridge.clients:
                return
            msg = {
                "type": "log",
                "level": record.levelname,
                "message": self.format(record),
                "timestamp": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "source": record.name,
            }
            loop = self.bridge._loop
            if loop and not loop.is_closed():
                asyncio.run_coroutine_threadsafe(self.bridge._broadcast(msg), loop)
        except Exception:
            pass  # Never let logging errors crash the app


class BridgeLogFilter(logging.Filter):
    """Keep high-signal logs to avoid flooding the TUI log stream."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("whisper_local"):
            return record.levelno >= logging.INFO
        return record.levelno >= logging.WARNING


class BridgeServer:
    """WebSocket server bridging the TypeScript TUI to Python backend."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.clients: set[WebSocketServerProtocol] = set()
        self._recording = False
        self._auto_copy = False
        self._busy_started_at = 0.0
        self._transcribing_jobs = 0
        self._status = "initializing"
        self._status_message = "Initializing..."
        self._model_loaded = False
        self._hotkey_started = False
        self._loop: asyncio.AbstractEventLoop | None = None

        # Audio/transcription components (initialized lazily)
        self.recorder: AudioRecorder | None = None
        self.noise: RNNoiseSuppressor | None = None
        self.vad: VadProcessor | None = None
        self.transcriber: Transcriber | None = None
        self.hotkey: HotkeyListener | None = None

    async def start(
        self,
        host: str = "localhost",
        port: int = 7878,
        capture_logs: bool = False,
    ) -> None:
        """Start the WebSocket server."""
        self._loop = asyncio.get_event_loop()

        if capture_logs:
            self._install_log_handler()

        self._init_components()

        # Start the WebSocket server FIRST so the TUI can connect immediately,
        # then load the model in the background while clients see the loading status.
        async with websockets.serve(self._handle_client, host, port):
            logger.info(f"Bridge server running on ws://{host}:{port}")
            await self._load_model_async()
            await asyncio.Future()  # Run forever

    def _install_log_handler(self) -> None:
        """Install WebSocket log handler on root logger and suppress stderr."""
        ws_handler = WebSocketLogHandler(self)
        ws_handler.setFormatter(logging.Formatter("%(message)s"))
        ws_handler.addFilter(BridgeLogFilter())

        root = logging.getLogger()
        # Remove all existing handlers to avoid any output to terminal
        root.handlers.clear()
        root.addHandler(ws_handler)
        root.setLevel(logging.INFO)

        # Suppress verbose third-party debug logs that can overwhelm the TUI.
        logging.getLogger("websockets").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)

    def _init_components(self) -> None:
        """Initialize audio and transcription components."""
        self.recorder = AudioRecorder(sample_rate=self.config.audio.sample_rate)
        self.noise = RNNoiseSuppressor(enabled=self.config.audio.noise_suppression.enabled)
        self.vad = VadProcessor(
            enabled=self.config.vad.enabled, aggressiveness=self.config.vad.aggressiveness
        )
        self.transcriber = Transcriber(
            model_name=self.config.model.name,
            device=self.config.model.device,
            compute_type=self.config.model.compute_type,
            model_path=self.config.model.path,
        )
        self.hotkey = HotkeyListener(
            self.config.hotkey.key,
            on_press=self._handle_hotkey_press,
            on_release=self._handle_hotkey_release,
        )

    async def _load_model_async(self) -> None:
        """Load the transcription model asynchronously."""
        await self._set_status("downloading", "Loading model...")
        try:
            if self.config.model.path:
                await self._set_status("downloading", "Loading local model...")
            else:
                installed = is_model_installed(self.config.model.name)
                if not installed and not self.config.model.auto_download:
                    await self._set_status(
                        "error",
                        f"Model {self.config.model.name} not installed. "
                        f"Run `whisper-local models pull {self.config.model.name}`.",
                    )
                    return
                if self.config.model.auto_download:
                    if not installed:
                        await self._set_status(
                            "downloading",
                            f"Model {self.config.model.name} not found. Downloading...",
                        )
                    else:
                        await self._set_status(
                            "downloading",
                            f"Verifying model {self.config.model.name}...",
                        )
                    model_path = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: ensure_model_available(self.config.model.name)
                    )
                    self.transcriber.model_path = str(model_path)
                    await self._set_status("downloading", "Model ready. Loading...")

            await asyncio.get_event_loop().run_in_executor(None, self.transcriber.load)
            self._model_loaded = True
            self._start_hotkey()
            await self._set_status("ready", "Ready")
        except Exception as exc:
            logger.exception("Model load failed")
            await self._set_status("error", f"Model load failed: {exc}")

    def _start_hotkey(self) -> None:
        """Start the hotkey listener."""
        if not self._hotkey_started and self.hotkey:
            self.hotkey.start()
            self._hotkey_started = True

    def _handle_hotkey_press(self) -> None:
        """Handle hotkey press event."""
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._on_hotkey_press(), self._loop)

    def _handle_hotkey_release(self) -> None:
        """Handle hotkey release event."""
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._on_hotkey_release(), self._loop)

    async def _on_hotkey_press(self) -> None:
        """Process hotkey press."""
        await self._broadcast({"type": "hotkey_press"})
        if self.config.hotkey.mode == "toggle":
            if self._recording:
                await self._stop_recording()
            else:
                await self._start_recording()
        else:
            await self._start_recording()

    async def _on_hotkey_release(self) -> None:
        """Process hotkey release."""
        await self._broadcast({"type": "hotkey_release"})
        if self.config.hotkey.mode == "ptt":
            await self._stop_recording()

    async def _start_recording(self) -> None:
        """Start audio recording."""
        if self._recording or not self.recorder:
            return
        self.recorder.start()
        self._recording = True
        await self._set_status("recording", "Recording...")

    async def _stop_recording(self) -> None:
        """Stop recording and process audio."""
        if not self._recording or not self.recorder:
            return
        audio = self.recorder.stop()
        self._recording = False

        if self._transcribing_jobs == 0:
            self._busy_started_at = monotonic()
        self._transcribing_jobs += 1

        await self._set_status("transcribing", "Transcribing...")

        # Process in background
        asyncio.create_task(self._process_audio(audio))

    async def _finalize_transcription_job(self, final_status: str, final_message: str) -> None:
        """Finalize one transcription task without regressing live recording state."""
        self._transcribing_jobs = max(0, self._transcribing_jobs - 1)

        if self._recording:
            await self._set_status("recording", "Recording...")
            return

        if self._transcribing_jobs > 0:
            await self._set_status("transcribing", "Transcribing...")
            return

        await self._set_status(final_status, final_message)

    async def _process_audio(self, audio) -> None:
        """Process recorded audio through noise/vad/transcription pipeline."""
        final_status = "ready"
        final_message = "Ready"

        if audio.size == 0:
            await self._finalize_transcription_job("ready", "No audio captured")
            return

        try:
            # Noise suppression
            if self.noise:
                noise_result = self.noise.process(audio, self.config.audio.sample_rate)
                audio = noise_result.audio

            # VAD
            if self.config.vad.enabled and self.vad:
                vad_result = self.vad.trim(audio, self.config.audio.sample_rate)
                audio = vad_result.audio

            # Transcription
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.transcriber.transcribe(
                    audio,
                    sample_rate=self.config.audio.sample_rate,
                    language=self.config.model.language,
                ),
            )

            if not result.text:
                await self._finalize_transcription_job("ready", "No speech detected")
                return

            timestamp = datetime.now().strftime("%H:%M:%S")
            await self._broadcast(
                {"type": "transcript", "timestamp": timestamp, "text": result.text}
            )

            # Handle output
            if self.config.output.clipboard or self._auto_copy:
                copy_to_clipboard(result.text)
            if self.config.output.file.enabled:
                append_to_file(self.config.output.file.path, result.text)
            final_status = "ready"
            final_message = "Ready"

        except Exception as exc:
            logger.exception("Transcription failed")
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Transcription failed: {exc}",
                    "level": "error",
                }
            )
            final_status = "error"
            final_message = f"Transcription failed: {exc}"
        finally:
            await self._finalize_transcription_job(final_status, final_message)

    async def _set_status(
        self, status: str, message: str, elapsed: float | None = None
    ) -> None:
        """Update and broadcast status."""
        self._status = status
        self._status_message = message
        msg: dict[str, Any] = {"type": "status", "status": status, "message": message}
        if elapsed is not None:
            msg["elapsed"] = int(elapsed)
        elif status in ("transcribing", "downloading") and self._busy_started_at:
            msg["elapsed"] = int(monotonic() - self._busy_started_at)
        await self._broadcast(msg)

    async def _broadcast(self, message: dict[str, Any]) -> None:
        """Send message to all connected clients."""
        if not self.clients:
            return
        data = json.dumps(message)
        await asyncio.gather(
            *[client.send(data) for client in self.clients], return_exceptions=True
        )

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a single client connection."""
        self.clients.add(websocket)
        logger.info(f"Client connected. Total clients: {len(self.clients)}")

        # Keep global hotkey capture active only while a client is connected.
        if self._model_loaded:
            self._start_hotkey()

        # Send current state
        await websocket.send(
            json.dumps({"type": "status", "status": self._status, "message": self._status_message})
        )
        await self._send_config(websocket)

        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            if not self.clients and self.hotkey and self._hotkey_started:
                self.hotkey.stop()
                self._hotkey_started = False
            logger.info(f"Client disconnected. Total clients: {len(self.clients)}")

    async def _handle_message(
        self, websocket: WebSocketServerProtocol, message: str
    ) -> None:
        """Handle incoming client message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "start_recording":
                await self._start_recording()
            elif msg_type == "stop_recording":
                await self._stop_recording()
            elif msg_type == "toggle_noise":
                await self._toggle_noise(data.get("enabled", True))
            elif msg_type == "toggle_vad":
                await self._toggle_vad(data.get("enabled", True))
            elif msg_type == "toggle_auto_copy":
                self._auto_copy = data.get("enabled", not self._auto_copy)
                await self._broadcast(
                    {"type": "toast", "message": f"Auto copy {'on' if self._auto_copy else 'off'}"}
                )
            elif msg_type == "download_model":
                await self._download_model(data.get("name", ""))
            elif msg_type == "remove_model":
                await self._remove_model(data.get("name", ""))
            elif msg_type == "set_default_model":
                await self._set_default_model(data.get("name", ""))
            elif msg_type == "set_hotkey":
                await self._set_hotkey(data.get("hotkey", ""))
            elif msg_type == "list_models":
                await self._send_models(websocket)
            elif msg_type == "get_config":
                await self._send_config(websocket)
            elif msg_type == "copy_text":
                text = data.get("text", "")
                if text:
                    copy_to_clipboard(text)
                    await self._broadcast({"type": "toast", "message": "Copied to clipboard"})
            elif msg_type == "get_config_file":
                await self._send_config_file(websocket)
            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError:
            logger.warning("Invalid JSON message received")
        except Exception:
            logger.exception("Error handling message")

    async def _toggle_noise(self, enabled: bool) -> None:
        """Toggle noise suppression."""
        self.config.audio.noise_suppression.enabled = enabled
        self.noise = RNNoiseSuppressor(enabled=enabled)
        save_config(self.config)
        state = "on" if enabled else "off"
        await self._broadcast({"type": "toast", "message": f"Noise suppression {state}"})
        await self._broadcast_config()

    async def _toggle_vad(self, enabled: bool) -> None:
        """Toggle VAD."""
        self.config.vad.enabled = enabled
        self.vad = VadProcessor(
            enabled=enabled, aggressiveness=self.config.vad.aggressiveness
        )
        save_config(self.config)
        state = "on" if enabled else "off"
        await self._broadcast({"type": "toast", "message": f"VAD {state}"})
        await self._broadcast_config()

    async def _download_model(self, name: str) -> None:
        """Download a model with progress reporting."""
        if not name:
            return
        await self._broadcast({"type": "toast", "message": f"Downloading {name}..."})

        loop = asyncio.get_event_loop()
        last_percent = -1

        def on_progress(percent: int) -> None:
            nonlocal last_percent
            # Throttle: only broadcast when percent actually changes
            if percent == last_percent:
                return
            last_percent = percent
            asyncio.run_coroutine_threadsafe(
                self._broadcast(
                    {"type": "download_progress", "model": name, "percent": percent}
                ),
                loop,
            )

        try:
            await loop.run_in_executor(
                None, lambda: download_model(name, progress_callback=on_progress)
            )
            # Send 100% to ensure TUI sees completion
            await self._broadcast(
                {"type": "download_progress", "model": name, "percent": 100}
            )
            await self._broadcast({"type": "toast", "message": f"Downloaded {name}"})
            await self._broadcast_models()
        except Exception as exc:
            await self._broadcast(
                {"type": "toast", "message": f"Download failed: {exc}", "level": "error"}
            )

    async def _remove_model(self, name: str) -> None:
        """Remove a model."""
        if not name:
            return
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: remove_model(name)
            )
            await self._broadcast({"type": "toast", "message": f"Removed {name}"})
            await self._broadcast_models()
        except Exception as exc:
            await self._broadcast(
                {"type": "toast", "message": f"Remove failed: {exc}", "level": "error"}
            )

    async def _set_default_model(self, name: str) -> None:
        """Set default model."""
        if not name:
            return
        try:
            set_default_model(name)
            self.config.model.name = name
            await self._broadcast({"type": "toast", "message": f"Default model set to {name}"})
            await self._broadcast_config()
        except ValueError as exc:
            await self._broadcast(
                {"type": "toast", "message": str(exc), "level": "error"}
            )

    async def _set_hotkey(self, hotkey: str) -> None:
        """Update and restart the global hotkey listener."""
        if not hotkey:
            await self._broadcast(
                {"type": "toast", "message": "Hotkey cannot be empty", "level": "error"}
            )
            return

        try:
            parse_hotkey(hotkey)
        except ValueError as exc:
            await self._broadcast(
                {"type": "toast", "message": f"Invalid hotkey: {exc}", "level": "error"}
            )
            return

        previous_hotkey = self.config.hotkey.key
        previous_listener = self.hotkey
        was_started = self._hotkey_started

        try:
            if previous_listener and was_started:
                previous_listener.stop()
                self._hotkey_started = False

            self.config.hotkey.key = hotkey
            self.hotkey = HotkeyListener(
                self.config.hotkey.key,
                on_press=self._handle_hotkey_press,
                on_release=self._handle_hotkey_release,
            )

            if self._model_loaded:
                self._start_hotkey()
        except Exception as exc:
            logger.exception("Failed to apply hotkey")
            self.config.hotkey.key = previous_hotkey
            self.hotkey = previous_listener
            self._hotkey_started = False
            if self._model_loaded and self.hotkey and was_started:
                try:
                    self._start_hotkey()
                except Exception:
                    logger.exception("Failed to restore previous hotkey listener")
            await self._broadcast(
                {"type": "toast", "message": f"Failed to apply hotkey: {exc}", "level": "error"}
            )
            return

        persist_error: str | None = None
        try:
            save_config(self.config)
        except Exception as exc:
            logger.exception("Failed to persist hotkey config")
            persist_error = str(exc)

        await self._broadcast_config()
        await self._broadcast({"type": "toast", "message": f"Hotkey set to {hotkey}"})
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Hotkey updated for this session, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _send_models(self, websocket: WebSocketServerProtocol) -> None:
        """Send model list to a client."""
        models = list_installed_models()
        await websocket.send(
            json.dumps({
                "type": "models",
                "models": [
                    {"name": m.name, "installed": m.installed, "path": str(m.path) if m.path else None}
                    for m in models
                ],
            })
        )

    async def _broadcast_models(self) -> None:
        """Broadcast model list to all clients."""
        models = list_installed_models()
        await self._broadcast({
            "type": "models",
            "models": [
                {"name": m.name, "installed": m.installed, "path": str(m.path) if m.path else None}
                for m in models
            ],
        })

    async def _send_config_file(self, websocket: WebSocketServerProtocol) -> None:
        """Send the raw TOML config file content to a client."""
        config_path = default_config_path()
        try:
            content = config_path.read_text() if config_path.exists() else ""
        except Exception as exc:
            logger.warning(f"Could not read config file: {exc}")
            content = ""
        await websocket.send(
            json.dumps({"type": "config_file", "content": content, "path": str(config_path)})
        )

    async def _send_config(self, websocket: WebSocketServerProtocol) -> None:
        """Send config to a client."""
        config_dict = self.config.to_dict()
        # Add bridge config
        config_dict["bridge"] = {"host": "localhost", "port": 7878}
        # Add auto_copy state
        config_dict["auto_copy"] = self._auto_copy
        await websocket.send(json.dumps({"type": "config", "config": config_dict}))

    async def _broadcast_config(self) -> None:
        """Broadcast config to all clients."""
        config_dict = self.config.to_dict()
        config_dict["bridge"] = {"host": "localhost", "port": 7878}
        config_dict["auto_copy"] = self._auto_copy
        await self._broadcast({"type": "config", "config": config_dict})

    def shutdown(self) -> None:
        """Clean up resources."""
        if self._hotkey_started and self.hotkey:
            self.hotkey.stop()
        if self.noise:
            self.noise.close()


def run_bridge(
    config: AppConfig | None = None,
    host: str = "localhost",
    port: int = 7878,
    capture_logs: bool = False,
) -> None:
    """Run the bridge server."""
    app_config = config or load_config()
    server = BridgeServer(app_config)
    try:
        asyncio.run(server.start(host, port, capture_logs=capture_logs))
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
