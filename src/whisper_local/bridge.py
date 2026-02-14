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
    MODEL_NAMES,
    download_model,
    list_installed_models,
    remove_model,
)
from whisper_local.noise import RNNoiseSuppressor
from whisper_local.output import append_to_file, copy_to_clipboard
from whisper_local.transcribe import (
    Transcriber,
    detect_runtime_capabilities,
    ensure_whisper_cpp_installed,
)
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
        # Benign noise: clients that connect then close before sending a full
        # HTTP upgrade request trigger this handshake traceback in websockets.
        # This is expected during reconnect races and should not pollute TUI logs.
        """
        Decides whether a logging record should be forwarded to the UI by applying source- and level-based filters.
        
        Parameters:
            record (logging.LogRecord): The log record to evaluate.
        
        Returns:
            bool: `True` if the record should be emitted to clients; `False` if it should be suppressed.
        
        Details:
        - Suppresses known benign websockets handshake noise (records from `websockets.server` or `websockets.asyncio.server` containing "opening handshake failed").
        - Allows logs from `whisper_local` at level INFO or higher.
        - Allows all other logs at level WARNING or higher.
        """
        if record.name in {"websockets.server", "websockets.asyncio.server"}:
            message = record.getMessage()
            if "opening handshake failed" in message:
                return False

        if record.name.startswith("whisper_local"):
            return record.levelno >= logging.INFO
        return record.levelno >= logging.WARNING


class BridgeServer:
    """WebSocket server bridging the TypeScript TUI to Python backend."""

    def __init__(self, config: AppConfig) -> None:
        """
        Initialize the bridge server state from the provided application configuration.
        
        Parameters:
            config (AppConfig): Application configuration used to populate runtime settings and persisted options. Components for audio capture, noise suppression, VAD, transcription, and hotkey handling are created lazily; runtime capability detection and a model reload lock are initialized eagerly.
        """
        self.config = config
        self.clients: set[WebSocketServerProtocol] = set()
        self._recording = False
        self._auto_copy = bool(config.auto_copy)
        self._busy_started_at = 0.0
        self._transcribing_jobs = 0
        self._hotkey_blocked = False
        self._status = "initializing"
        self._status_message = "Initializing..."
        self._model_loaded = False
        self._hotkey_started = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._model_reload_lock = asyncio.Lock()
        self._runtime_capabilities = self._detect_runtime_capabilities()

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
        """
        Start and run the Bridge WebSocket server: initialize runtime components, accept client connections on the given host and port, and load the transcription model in the background.
        
        This method initializes internal components, optionally installs a WebSocket log handler when capture_logs is True, starts serving clients at ws://{host}:{port}, begins model loading once the server is listening, and then runs indefinitely until cancelled.
        
        Parameters:
            host (str): Hostname or IP address to bind the WebSocket server to.
            port (int): TCP port to listen on.
            capture_logs (bool): If True, route Python log records to connected WebSocket clients by installing the WebSocket log handler.
        """
        self._loop = asyncio.get_event_loop()

        ensure_whisper_cpp_installed()

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
            backend=self.config.model.backend,
            device=self.config.model.device,
            compute_type=self.config.model.compute_type,
            model_path=self.config.model.path,
            auto_download=self.config.model.auto_download,
        )
        self.hotkey = HotkeyListener(
            self.config.hotkey.key,
            on_press=self._handle_hotkey_press,
            on_release=self._handle_hotkey_release,
        )

    def _detect_runtime_capabilities(self) -> dict[str, Any]:
        """
        Detects runtime capabilities for the currently configured model backend.
        
        Returns:
            dict[str, Any]: Mapping of runtime capability names (for example supported backends, available devices, supported compute types, and related flags) to their detected values.
        """
        return detect_runtime_capabilities(self.config.model.backend)

    def _refresh_runtime_capabilities(self) -> None:
        """
        Refresh the cached runtime capabilities by re-running capability detection and storing the result on the instance.
        
        This updates the internal `self._runtime_capabilities` attribute with the latest detected capabilities.
        """
        self._runtime_capabilities = self._detect_runtime_capabilities()

    async def _load_model_async(self) -> None:
        """
        Load and activate the configured transcription model.
        
        Updates the bridge status to indicate model downloading, loads the model, marks the model as loaded, starts the hotkey listener, logs runtime information about the loaded transcriber, and updates the status to ready. If loading fails, logs the exception and sets the bridge status to error with the failure message.
        """
        await self._set_status(
            "downloading",
            f"Loading {self.config.model.backend} model {self.config.model.name}...",
        )
        try:
            if self.transcriber is None:
                raise RuntimeError("Transcriber is not initialized")

            await asyncio.get_event_loop().run_in_executor(None, self.transcriber.load)
            self._model_loaded = True
            self._start_hotkey()
            info = self.transcriber.runtime_info()
            logger.info(
                "Transcriber ready backend=%s model=%s device=%s compute_type=%s source=%s",
                info.get("backend", "unknown"),
                info.get("model_name", self.config.model.name),
                info.get("effective_device", "unknown"),
                info.get("effective_compute_type", "unknown"),
                info.get("model_source", "unknown"),
            )
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
        if self._hotkey_blocked:
            logger.debug("Ignoring hotkey press while dialog is open")
            return

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
        """
        Stop active audio capture, mark the server as not recording, and schedule transcription of the captured audio in the background.
        
        If no recording is active this is a no-op. When audio is captured the function updates internal recording and job counters, sets the status to "transcribing", records a busy-start timestamp if this is the first transcription job, and enqueues a background task to process the audio with the current transcriber, language, and sample rate.
        """
        if not self._recording or not self.recorder:
            return
        audio = self.recorder.stop()
        self._recording = False

        job_transcriber = self.transcriber
        job_language = self.config.model.language
        job_sample_rate = self.config.audio.sample_rate

        if self._transcribing_jobs == 0:
            self._busy_started_at = monotonic()
        self._transcribing_jobs += 1

        await self._set_status("transcribing", "Transcribing...")

        # Process in background
        asyncio.create_task(
            self._process_audio(
                audio,
                transcriber=job_transcriber,
                language=job_language,
                sample_rate=job_sample_rate,
            )
        )

    async def _finalize_transcription_job(self, final_status: str, final_message: str) -> None:
        """
        Finalize a completed transcription job and update the server status without interrupting active recording.
        
        Decrements the in-flight transcription job counter. If recording is currently active, the status is set to "recording". If other transcription jobs remain, the status is set to "transcribing". When no recording or transcribing remains, sets the status to the provided final status and message.
        
        Parameters:
            final_status (str): Status to set when there are no ongoing recordings or transcriptions (e.g., "ready", "error").
            final_message (str): Human-readable message associated with `final_status`.
        """
        self._transcribing_jobs = max(0, self._transcribing_jobs - 1)

        if self._recording:
            await self._set_status("recording", "Recording...")
            return

        if self._transcribing_jobs > 0:
            await self._set_status("transcribing", "Transcribing...")
            return

        await self._set_status(final_status, final_message)

    async def _process_audio(
        self,
        audio,
        *,
        transcriber: Transcriber | None = None,
        language: str | None = None,
        sample_rate: int | None = None,
    ) -> None:
        """
        Process a chunk of recorded audio through suppression, VAD trimming, transcription, and output handling, then update bridge status.
        
        Processes the provided audio (numpy-like array) using optional noise suppression and voice-activity detection, transcribes the resulting audio with the given or configured Transcriber, and emits results and state updates to connected clients. Side effects include broadcasting a `transcript` message, sending error or info toasts, optionally copying text to the clipboard or appending it to the configured output file, logging benchmark metrics, and finalizing the transcription job state.
        
        Parameters:
            audio (numpy.ndarray): 1-D array of raw audio samples to process.
            transcriber (Transcriber | None): Optional transcriber to use for this job; if None, uses the server's current transcriber.
            language (str | None): Optional language code to request for transcription; `None` requests automatic language detection.
            sample_rate (int | None): Sample rate of `audio` in Hz; if `None`, the server's configured audio sample rate is used.
        """
        final_status = "ready"
        final_message = "Ready"
        pipeline_started = monotonic()

        job_transcriber = transcriber or self.transcriber
        job_language = language
        job_sample_rate = sample_rate or self.config.audio.sample_rate
        input_samples = int(audio.shape[0])

        noise_enabled = bool(self.noise and self.noise.enabled)
        noise_available = bool(self.noise and self.noise.available)
        noise_applied = False
        noise_backend = getattr(self.noise, "_backend", "none") if self.noise else "none"

        vad_enabled = bool(self.config.vad.enabled and self.vad)
        vad_available = bool(self.vad and getattr(self.vad, "_vad", None))
        vad_applied = False

        post_noise_samples = input_samples
        post_vad_samples = input_samples
        transcribe_ms = 0
        output_language: str | None = None

        if audio.size == 0:
            await self._finalize_transcription_job("ready", "No audio captured")
            return

        if job_transcriber is None:
            await self._finalize_transcription_job("error", "Model is not loaded")
            return

        try:
            # Noise suppression
            if self.noise:
                noise_result = self.noise.process(audio, job_sample_rate)
                audio = noise_result.audio
                noise_available = noise_result.available
                noise_applied = noise_result.applied
                post_noise_samples = int(audio.shape[0])

            # VAD
            if self.config.vad.enabled and self.vad:
                vad_result = self.vad.trim(audio, job_sample_rate)
                audio = vad_result.audio
                vad_available = vad_result.available
                vad_applied = vad_result.applied

            post_vad_samples = int(audio.shape[0])

            # Transcription
            transcribe_started = monotonic()
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: job_transcriber.transcribe(
                    audio,
                    sample_rate=job_sample_rate,
                    language=job_language,
                ),
            )
            transcribe_ms = int((monotonic() - transcribe_started) * 1000)
            output_language = result.language

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
            total_ms = int((monotonic() - pipeline_started) * 1000)
            input_ms = int((input_samples / job_sample_rate) * 1000) if job_sample_rate > 0 else 0
            post_noise_ms = (
                int((post_noise_samples / job_sample_rate) * 1000) if job_sample_rate > 0 else 0
            )
            post_vad_ms = int((post_vad_samples / job_sample_rate) * 1000) if job_sample_rate > 0 else 0
            preprocess_ms = max(0, total_ms - transcribe_ms)
            rtf = (transcribe_ms / input_ms) if input_ms > 0 else 0.0
            backend_info = job_transcriber.runtime_info()

            logger.info(
                "bench backend=%s model_size=%s device=%s compute_type=%s input_ms=%d post_noise_ms=%d post_ms=%d "
                "noise(enabled=%s,available=%s,applied=%s,backend=%s) "
                "vad(enabled=%s,available=%s,applied=%s) preprocess_ms=%d transcribe_ms=%d total_ms=%d rtf=%.3f "
                "language(requested=%s,detected=%s)",
                backend_info.get("backend", self.config.model.backend),
                backend_info.get("model_name", self.config.model.name),
                backend_info.get("effective_device", self.config.model.device),
                backend_info.get("effective_compute_type", self.config.model.compute_type),
                input_ms,
                post_noise_ms,
                post_vad_ms,
                noise_enabled,
                noise_available,
                noise_applied,
                noise_backend,
                vad_enabled,
                vad_available,
                vad_applied,
                preprocess_ms,
                transcribe_ms,
                total_ms,
                rtf,
                job_language if job_language else "auto",
                output_language if output_language else "unknown",
            )

            await self._finalize_transcription_job(final_status, final_message)

    async def _set_status(
        self, status: str, message: str, elapsed: float | None = None
    ) -> None:
        """
        Update the server status and broadcast a status payload to connected clients.
        
        Parameters:
            status (str): New status identifier (e.g., "ready", "recording", "transcribing", "downloading", "error").
            message (str): Human-readable status message to include in the payload.
            elapsed (float | None): If provided, include this elapsed time in seconds (converted to int) in the payload.
                If omitted and the status is "transcribing" or "downloading" and a busy start time exists,
                elapsed is computed as the time since that busy start.
        
        The broadcasted payload contains: `type: "status"`, `status`, `message`, and an optional integer `elapsed`.
        """
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
            if not self.clients:
                self._hotkey_blocked = False
            logger.info(f"Client disconnected. Total clients: {len(self.clients)}")

    async def _handle_message(
        self, websocket: WebSocketServerProtocol, message: str
    ) -> None:
        """
        Dispatches a parsed client JSON message to the appropriate bridge action.
        
        Accepts a JSON-encoded command in `message`, routes it to the matching handler (recording control, noise/VAD toggles, auto-copy config, hotkey and hotkey mode updates, model management and selection, device/compute/language settings, model download/remove, config/model queries, and clipboard copy), persists config changes when applicable, and broadcasts user-facing toasts or updated config/state to connected clients. Invalid JSON or unknown message types are logged.
        """
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
                self._auto_copy = bool(data.get("enabled", not self._auto_copy))
                self.config.auto_copy = self._auto_copy
                persist_error: str | None = None
                try:
                    save_config(self.config)
                except Exception as exc:
                    logger.exception("Failed to persist auto copy config")
                    persist_error = str(exc)
                await self._broadcast(
                    {"type": "toast", "message": f"Auto copy {'on' if self._auto_copy else 'off'}"}
                )
                if persist_error:
                    await self._broadcast(
                        {
                            "type": "toast",
                            "message": f"Auto copy updated for this session, but failed to save: {persist_error}",
                            "level": "error",
                        }
                    )
                await self._broadcast_config()
            elif msg_type == "set_hotkey_blocked":
                self._hotkey_blocked = bool(data.get("enabled", False))
            elif msg_type == "set_hotkey_mode":
                await self._set_hotkey_mode(data.get("mode", ""))
            elif msg_type == "set_model_backend":
                await self._set_model_backend(data.get("backend", ""))
            elif msg_type == "set_model_device":
                await self._set_model_device(data.get("device", ""))
            elif msg_type == "set_model_compute_type":
                await self._set_model_compute_type(data.get("compute_type", ""))
            elif msg_type == "set_model_language":
                await self._set_model_language(data.get("language"))
            elif msg_type == "download_model":
                await self._download_model(data.get("name", ""))
            elif msg_type == "remove_model":
                await self._remove_model(data.get("name", ""))
            elif msg_type == "set_selected_model":
                await self._set_selected_model(data.get("name", ""))
            elif msg_type == "set_default_model":
                # Backward compatibility with older clients.
                await self._set_selected_model(data.get("name", ""))
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
        """
        Remove an installed model by name and notify connected clients of the result.
        
        If `name` is empty this is a no-op. On success broadcasts a success toast and refreshes the model list to all clients; on failure broadcasts an error toast containing the exception message.
        
        Parameters:
            name (str): The model name to remove. If empty, the function returns without action.
        """
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

    async def _set_selected_model(self, name: str) -> None:
        """
        Set the active model by name and attempt to apply it.
        
        If the given name is not a known model the client is notified and the current config is re-broadcast.
        On a valid name the config is updated and a transcriber reload is attempted. If reloading fails the previous
        model selection is restored, the failure is broadcast to clients, and the rollback save error (if any) is also
        notified. If applying succeeds but saving the new config fails, a notification is sent.
        
        Parameters:
            name (str): Name of the model to select. An empty string is treated as a no-op.
        """
        if not name:
            return

        known_models = set(MODEL_NAMES)
        if name not in known_models:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Unknown model: {name}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        previous_name = self.config.model.name
        previous_path = self.config.model.path

        self.config.model.name = name
        self.config.model.path = None

        persist_error = self._persist_config("selected model")

        try:
            await self._reload_transcriber()
        except Exception as exc:
            logger.exception("Failed to apply selected model")
            self.config.model.name = previous_name
            self.config.model.path = previous_path
            rollback_error = self._persist_config("selected model rollback")
            await self._broadcast_config()
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Failed to apply selected model: {exc}",
                    "level": "error",
                }
            )
            if rollback_error:
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Rollback config save failed: {rollback_error}",
                        "level": "error",
                    }
                )
            return

        await self._broadcast_config()
        await self._broadcast({"type": "toast", "message": f"Selected model set to {name}"})
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Selected model applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    def _persist_config(self, context: str) -> str | None:
        """
        Persist the server's configuration to disk.
        
        Parameters:
            context (str): Short description of what part of the system triggered the persist operation; used in error logging.
        
        Returns:
            error (str) | None: Error message if persisting failed, otherwise `None`.
        """
        try:
            save_config(self.config)
        except Exception as exc:
            logger.exception("Failed to persist %s config", context)
            return str(exc)
        return None

    async def _reload_transcriber(self) -> None:
        """
        Reload the transcriber from the current model configuration and install it on the server.
        
        Creates a new Transcriber using the current model settings, loads it in a thread executor, replaces the server's active transcriber with the newly loaded instance, marks the model as loaded, and refreshes runtime capability information. This operation is serialized using the instance's model reload lock to prevent concurrent reloads.
        """
        async with self._model_reload_lock:
            next_transcriber = Transcriber(
                model_name=self.config.model.name,
                backend=self.config.model.backend,
                device=self.config.model.device,
                compute_type=self.config.model.compute_type,
                model_path=self.config.model.path,
                auto_download=self.config.model.auto_download,
            )
            await asyncio.get_event_loop().run_in_executor(None, next_transcriber.load)
            self.transcriber = next_transcriber
            self._model_loaded = True
            self._refresh_runtime_capabilities()

    async def _set_model_backend(self, backend_name: str) -> None:
        """
        Change the active transcription model backend, validate it against runtime capabilities, and apply related configuration updates.
        
        If the requested backend is unsupported or unavailable on the current runtime, a client-facing error message is broadcast and the configuration is not changed. When the backend is switched successfully, the function adjusts device and compute-type settings to values supported by the new backend, persists the updated configuration, reloads the transcriber, and broadcasts the updated config and a success toast. If reloading the transcriber fails, the previous configuration is restored, persisted, and error toasts are broadcast.
        
        Parameters:
            backend_name (str): Backend identifier or alias (examples: "faster-whisper", "whisper.cpp", or aliases like "whispercpp"). The name is normalized before validation.
        """
        normalized = str(backend_name).strip().lower()
        if normalized in {"whispercpp", "whisper_cpp", "whisper-cpp"}:
            normalized = "whisper.cpp"

        supported = {"faster-whisper", "whisper.cpp"}
        if normalized not in supported:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Invalid model backend: {backend_name}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        capabilities = detect_runtime_capabilities(normalized)
        backend_options = capabilities.get("model", {}).get("backends", {})
        backend_state = backend_options.get(normalized, {"enabled": False, "reason": "Unsupported"})
        if not backend_state.get("enabled", False):
            await self._broadcast(
                {
                    "type": "toast",
                    "message": (
                        f"Backend {normalized} unavailable: "
                        f"{backend_state.get('reason', 'unsupported')}"
                    ),
                    "level": "error",
                }
            )
            self._runtime_capabilities = capabilities
            await self._broadcast_config()
            return

        if self.config.model.backend == normalized:
            self._runtime_capabilities = capabilities
            await self._broadcast_config()
            return

        previous_backend = self.config.model.backend
        previous_device = self.config.model.device
        previous_compute_type = self.config.model.compute_type
        self.config.model.backend = normalized
        self._runtime_capabilities = capabilities

        runtime_model = capabilities.get("model", {})
        runtime_devices = runtime_model.get("devices", {})
        current_device_state = runtime_devices.get(self.config.model.device, {"enabled": False})
        if not current_device_state.get("enabled", False):
            for candidate in ("mps", "cpu", "cuda"):
                candidate_state = runtime_devices.get(candidate, {"enabled": False})
                if candidate_state.get("enabled", False):
                    self.config.model.device = candidate
                    break

        compute_map = runtime_model.get("compute_types_by_device", {})
        valid_compute_types = {
            str(item).strip().lower()
            for item in compute_map.get(self.config.model.device, [])
            if str(item).strip()
        }
        if valid_compute_types and self.config.model.compute_type not in valid_compute_types:
            for candidate in (
                "int8",
                "default",
                "int8_float32",
                "float32",
                "float16",
                "int8_float16",
            ):
                if candidate in valid_compute_types:
                    self.config.model.compute_type = candidate
                    break
            else:
                self.config.model.compute_type = sorted(valid_compute_types)[0]

        persist_error = self._persist_config("model backend")

        try:
            await self._reload_transcriber()
        except Exception as exc:
            logger.exception("Failed to apply model backend")
            self.config.model.backend = previous_backend
            self.config.model.device = previous_device
            self.config.model.compute_type = previous_compute_type
            self._runtime_capabilities = detect_runtime_capabilities(previous_backend)
            rollback_error = self._persist_config("model backend rollback")
            await self._broadcast_config()
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Failed to apply model backend: {exc}",
                    "level": "error",
                }
            )
            if rollback_error:
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Rollback config save failed: {rollback_error}",
                        "level": "error",
                    }
                )
            return

        await self._broadcast_config()
        await self._broadcast({"type": "toast", "message": f"Model backend {normalized}"})
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model backend applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_model_device(self, device: str) -> None:
        """
        Set the target compute device for the transcription model.
        
        Updates the server config to use the specified device ("cpu", "cuda", or "mps"), validates availability against detected runtime capabilities, persists the change, and attempts to reload the transcriber. On success broadcasts the updated config and a confirmation toast; on failure restores the previous device, persists the rollback, and broadcasts error toasts. Also refreshes runtime capability information before validation.
        
        Parameters:
            device (str): Desired model device identifier (e.g., "cpu", "cuda", "mps").
        """
        self._refresh_runtime_capabilities()
        normalized = str(device).strip().lower()
        if normalized not in {"cpu", "cuda", "mps"}:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Invalid model device: {device}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        runtime_devices = self._runtime_capabilities.get("model", {}).get("devices", {})
        runtime_device = runtime_devices.get(normalized)
        if runtime_device and not runtime_device.get("enabled", False):
            reason = runtime_device.get("reason") or "Unsupported on this machine"
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model device {normalized} unavailable: {reason}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        if self.config.model.device == normalized:
            return

        previous_device = self.config.model.device
        self.config.model.device = normalized
        persist_error = self._persist_config("model device")

        try:
            await self._reload_transcriber()
        except Exception as exc:
            logger.exception("Failed to apply model device")
            self.config.model.device = previous_device
            rollback_error = self._persist_config("model device rollback")
            await self._broadcast_config()
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Failed to apply model device: {exc}",
                    "level": "error",
                }
            )
            if rollback_error:
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Rollback config save failed: {rollback_error}",
                        "level": "error",
                    }
                )
            return

        await self._broadcast_config()
        await self._broadcast({"type": "toast", "message": f"Model device {normalized}"})
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model device applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_model_compute_type(self, compute_type: str) -> None:
        """
        Validate and apply a new model compute type, persist the change, reload the transcriber, and notify connected clients.
        
        Validates the provided compute type against allowed values and the runtime capabilities for the currently selected device, broadcasts error toasts and the current config when validation fails, updates the configured compute type when valid, attempts to reload the transcriber, and rolls back the configuration on failure. On success broadcasts the updated config and a success toast; if saving the config fails the failure is reported as an error toast.
        
        Parameters:
            compute_type (str): Compute type to apply (case-insensitive, trimmed). Examples include "default", "int8", "float16", "float32", "int8_float16", "int8_float32".
        """
        self._refresh_runtime_capabilities()
        normalized = str(compute_type).strip().lower()
        allowed = {"default", "int8", "float16", "float32", "int8_float16", "int8_float32"}
        if normalized not in allowed:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Invalid compute type: {compute_type}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        runtime_model = self._runtime_capabilities.get("model", {})
        current_device = self.config.model.device.lower().strip()
        supported_for_device = {
            str(item).strip().lower()
            for item in runtime_model.get("compute_types_by_device", {}).get(current_device, [])
            if str(item).strip()
        }

        if current_device == "cpu" and normalized in {"float16", "int8_float16"}:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": "Selected compute type is not usable on CPU (falls back to int8)",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        if supported_for_device and normalized not in supported_for_device:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Compute type {normalized} unsupported on {current_device}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        if self.config.model.compute_type == normalized:
            return

        previous_compute_type = self.config.model.compute_type
        self.config.model.compute_type = normalized
        persist_error = self._persist_config("model compute type")

        try:
            await self._reload_transcriber()
        except Exception as exc:
            logger.exception("Failed to apply model compute type")
            self.config.model.compute_type = previous_compute_type
            rollback_error = self._persist_config("model compute type rollback")
            await self._broadcast_config()
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Failed to apply compute type: {exc}",
                    "level": "error",
                }
            )
            if rollback_error:
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Rollback config save failed: {rollback_error}",
                        "level": "error",
                    }
                )
            return

        await self._broadcast_config()
        await self._broadcast({"type": "toast", "message": f"Compute type {normalized}"})
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Compute type applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_model_language(self, language: Any) -> None:
        """
        Update the configured transcription language and notify connected clients.
        
        Sets the bridge's model language to the provided value (treating "", "auto", "none", or None as automatic language detection), persists the configuration, and broadcasts the updated config and a user-facing toast. If saving the configuration fails, broadcasts an error toast indicating the persistence failure.
        
        Parameters:
        	language (Any): The desired language name or identifier; values that are empty, "auto", "none", or None enable automatic language detection.
        """
        raw = "" if language is None else str(language)
        normalized = raw.strip().lower()
        if normalized in {"", "auto", "none"}:
            next_language: str | None = None
        else:
            next_language = normalized

        if self.config.model.language == next_language:
            return

        self.config.model.language = next_language
        persist_error = self._persist_config("model language")

        await self._broadcast_config()
        await self._broadcast(
            {
                "type": "toast",
                "message": (
                    "Model language auto"
                    if next_language is None
                    else f"Model language {next_language}"
                ),
            }
        )

        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model language applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_hotkey(self, hotkey: str) -> None:
        """
        Set and activate a new global hotkey and persist the change.
        
        Validates the provided hotkey string; if empty or invalid, broadcasts an error toast and returns.
        Stops and replaces the current hotkey listener, starts the new listener if a model is loaded, and rolls back to the previous listener on failure while broadcasting an error toast. Persists the updated config; always broadcasts the updated config and a success toast, and broadcasts an error toast if persisting the config fails.
        
        Parameters:
            hotkey (str): Hotkey specification string to apply (must be non-empty and parseable).
        """
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

    async def _set_hotkey_mode(self, mode: str) -> None:
        """Update hotkey mode (ptt/toggle) and persist config."""
        normalized = str(mode).strip().lower()
        if normalized not in ("ptt", "toggle"):
            await self._broadcast(
                {
                    "type": "toast",
                    "message": "Invalid hotkey mode (expected ptt or toggle)",
                    "level": "error",
                }
            )
            return

        if self.config.hotkey.mode == normalized:
            return

        self.config.hotkey.mode = normalized

        persist_error: str | None = None
        try:
            save_config(self.config)
        except Exception as exc:
            logger.exception("Failed to persist hotkey mode config")
            persist_error = str(exc)

        await self._broadcast_config()
        await self._broadcast({"type": "toast", "message": f"Hotkey mode {normalized}"})

        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Hotkey mode updated for this session, but failed to save: {persist_error}",
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
        """
        Send the current configuration payload to the given client.
        
        The payload includes the bridge configuration augmented with runtime capabilities and bridge metadata and is sent as a JSON message with type "config".
        """
        await websocket.send(json.dumps({"type": "config", "config": self._config_payload()}))

    async def _broadcast_config(self) -> None:
        """
        Broadcast the current configuration payload to all connected clients.
        
        Sends a message with type `"config"` whose `config` field contains the current config payload (includes runtime capabilities and bridge metadata).
        """
        await self._broadcast({"type": "config", "config": self._config_payload()})

    def _config_payload(self) -> dict[str, Any]:
        """
        Builds and returns the configuration payload sent to clients.
        
        Refreshes the server's runtime capability snapshot, then returns a dictionary representation of the current configuration augmented with:
        - "bridge": dict with "host" and "port" of the bridge,
        - "auto_copy": boolean indicating whether automatic copy-to-clipboard is enabled,
        - "runtime": the latest runtime capability information.
        
        Returns:
            config_payload (dict[str, Any]): The full config payload ready for broadcasting to clients.
        """
        self._refresh_runtime_capabilities()
        config_dict = self.config.to_dict()
        config_dict["bridge"] = {"host": "localhost", "port": 7878}
        config_dict["auto_copy"] = self._auto_copy
        config_dict["runtime"] = self._runtime_capabilities
        return config_dict

    def shutdown(self) -> None:
        """
        Stop any running hotkey listener and release audio/noise-suppression resources.
        
        Stops the hotkey listener if it was started, and closes the noise suppressor if present to free underlying resources.
        """
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