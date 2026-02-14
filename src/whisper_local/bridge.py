"""WebSocket bridge server for TypeScript TUI communication."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import threading
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import websockets
from websockets.server import WebSocketServerProtocol

from whisper_local.audio import AudioRecorder
from whisper_local.audio_file import load_audio_file
from whisper_local.config import AppConfig, default_config_path, load_config, save_config
from whisper_local.hotkey import HotkeyListener, parse_hotkey
from whisper_local.model_manager import (
    DownloadCancelledError,
    MODEL_NAMES,
    download_model,
    get_installed_model_path,
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

MAX_DROP_FILES = 32
MAX_DROP_FILE_BYTES = 512 * 1024 * 1024
MAX_DROP_AUDIO_SECONDS = 4 * 60 * 60


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
        self.config = config
        self.clients: set[WebSocketServerProtocol] = set()
        self._passive_clients: set[WebSocketServerProtocol] = set()
        self._recording = False
        self._auto_copy = bool(config.auto_copy)
        self._busy_started_at = 0.0
        self._transcribing_jobs = 0
        self._hotkey_blocked = False
        self._status = "initializing"
        self._status_message = "Initializing..."
        self._model_loaded = False
        self._first_run_setup_required = False
        self._hotkey_started = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._model_reload_lock = asyncio.Lock()
        self._model_op_lock = asyncio.Lock()
        self._file_transcription_lock = asyncio.Lock()
        self._runtime_capabilities = self._detect_runtime_capabilities()
        self._shutdown_requested = threading.Event()

        self._background_tasks: set[asyncio.Task] = set()

        # Audio/transcription components (initialized lazily)
        self.recorder: AudioRecorder | None = None
        self.noise: RNNoiseSuppressor | None = None
        self.vad: VadProcessor | None = None
        self.transcriber: Transcriber | None = None
        self.hotkey: HotkeyListener | None = None

    def _spawn_task(self, coro) -> asyncio.Task:
        """Create a background task and prevent it from being garbage-collected."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _client_path(self, websocket: WebSocketServerProtocol) -> str:
        """Return connection path across websockets API versions."""
        # websockets <=13 exposes `.path` directly.
        legacy_path = getattr(websocket, "path", None)
        if isinstance(legacy_path, str):
            return legacy_path

        # websockets >=14 exposes `.request.path`.
        request = getattr(websocket, "request", None)
        request_path = getattr(request, "path", None) if request is not None else None
        if isinstance(request_path, str):
            return request_path

        return ""

    def _is_passive_client(self, websocket: WebSocketServerProtocol) -> bool:
        path = self._client_path(websocket)
        if not path:
            return False
        try:
            query = parse_qs(urlparse(path).query)
        except Exception:
            return False
        client_type = query.get("client", [""])[0].strip().lower()
        return client_type in {"status-indicator", "passive"}

    def _has_active_clients(self) -> bool:
        return any(client not in self._passive_clients for client in self.clients)

    def _active_client_count(self) -> int:
        return sum(1 for client in self.clients if client not in self._passive_clients)

    def _installed_model_names(self) -> list[str]:
        return [model.name for model in list_installed_models() if model.installed]

    def _has_installed_models(self) -> bool:
        return bool(self._installed_model_names())

    async def start(
        self,
        host: str = "localhost",
        port: int = 7878,
        capture_logs: bool = False,
    ) -> None:
        """Start the WebSocket server."""
        self._loop = asyncio.get_event_loop()

        ensure_whisper_cpp_installed()

        if capture_logs:
            self._install_log_handler()

        self._init_components()
        self._first_run_setup_required = not self._has_installed_models()

        # Start the WebSocket server FIRST so the TUI can connect immediately,
        # then load the model in the background while clients see the loading status.
        async with websockets.serve(self._handle_client, host, port):
            logger.info(f"Bridge server running on ws://{host}:{port}")
            if self._first_run_setup_required:
                await self._set_status(
                    "connecting",
                    "First run setup required. Download and select a model in Model Manager.",
                )
            else:
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
        return detect_runtime_capabilities(self.config.model.backend)

    def _refresh_runtime_capabilities(self) -> None:
        self._runtime_capabilities = self._detect_runtime_capabilities()

    async def _load_model_async(self) -> None:
        """Load the transcription model asynchronously."""
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
            self._first_run_setup_required = False
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
        """Stop recording and process audio."""
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
        self._spawn_task(
            self._process_audio(
                audio,
                transcriber=job_transcriber,
                language=job_language,
                sample_rate=job_sample_rate,
            )
        )

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

    async def _process_audio(
        self,
        audio,
        *,
        transcriber: Transcriber | None = None,
        language: str | None = None,
        sample_rate: int | None = None,
        source_label: str | None = None,
    ) -> tuple[str, str]:
        """Process recorded audio through noise/vad/transcription pipeline."""
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
            final_message = "No audio captured"
            await self._finalize_transcription_job(final_status, final_message)
            return final_status, final_message

        if job_transcriber is None:
            final_status = "error"
            final_message = "Model is not loaded"
            await self._finalize_transcription_job(final_status, final_message)
            return final_status, final_message

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
                final_status = "ready"
                final_message = "No speech detected"
                return final_status, final_message

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
            error_prefix = "Transcription failed"
            if source_label:
                error_prefix = f"Transcription failed ({source_label})"
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"{error_prefix}: {exc}",
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

        return final_status, final_message

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
        passive_client = self._is_passive_client(websocket)
        if passive_client:
            self._passive_clients.add(websocket)
        logger.info(
            "Client connected. total=%d active=%d passive=%d",
            len(self.clients),
            self._active_client_count(),
            len(self._passive_clients),
        )

        # Keep global hotkey capture active only while a client is connected.
        if self._model_loaded and self._has_active_clients():
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
            self._passive_clients.discard(websocket)
            if not self._has_active_clients() and self.hotkey and self._hotkey_started:
                self.hotkey.stop()
                self._hotkey_started = False
            if not self.clients:
                self._hotkey_blocked = False
            logger.info(
                "Client disconnected. total=%d active=%d passive=%d",
                len(self.clients),
                self._active_client_count(),
                len(self._passive_clients),
            )

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
                self._spawn_task(self._download_model(data.get("name", "")))
            elif msg_type == "remove_model":
                self._spawn_task(self._remove_model(data.get("name", "")))
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
            elif msg_type == "transcribe_paste":
                self._spawn_task(self._handle_transcribe_paste(data.get("text", "")))
            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError:
            logger.warning("Invalid JSON message received")
        except Exception:
            logger.exception("Error handling message")

    async def _handle_transcribe_paste(self, raw_text: Any) -> None:
        text = str(raw_text or "").strip()
        if not text:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": "No file path received from paste",
                    "level": "error",
                }
            )
            return

        parsed_paths = self._extract_paths_from_paste(text)
        if not parsed_paths:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": "Could not parse any file paths from paste",
                    "level": "error",
                }
            )
            return

        valid_paths: list[Path] = []
        seen: set[str] = set()
        for path in parsed_paths:
            normalized = str(path)
            if normalized in seen:
                continue
            seen.add(normalized)

            if not path.exists():
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"File not found: {path}",
                        "level": "error",
                    }
                )
                continue
            if not path.is_file():
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Not a file: {path}",
                        "level": "error",
                    }
                )
                continue

            valid_paths.append(path)

        if not valid_paths:
            return

        if len(valid_paths) > MAX_DROP_FILES:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": (
                        f"Paste contained {len(valid_paths)} files; processing first {MAX_DROP_FILES}."
                    ),
                    "level": "error",
                }
            )
            valid_paths = valid_paths[:MAX_DROP_FILES]

        if len(valid_paths) == 1:
            await self._broadcast(
                {"type": "toast", "message": f"Queued file transcription: {valid_paths[0].name}"}
            )
        else:
            await self._broadcast(
                {"type": "toast", "message": f"Queued {len(valid_paths)} files for transcription"}
            )

        async with self._file_transcription_lock:
            for path in valid_paths:
                await self._transcribe_audio_file(path)

    def _extract_paths_from_paste(self, text: str) -> list[Path]:
        tokens: list[str] = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            lines = [text.strip()]

        for line in lines:
            try:
                line_tokens = shlex.split(line, posix=True)
            except ValueError:
                line_tokens = [line]
            if line_tokens:
                tokens.extend(line_tokens)

        paths: list[Path] = []
        for token in tokens:
            normalized = self._normalize_paste_path(token)
            if normalized is not None:
                paths.append(normalized)
        return paths

    def _normalize_paste_path(self, token: str) -> Path | None:
        candidate = token.strip()
        if not candidate:
            return None

        if candidate.startswith("file://"):
            parsed = urlparse(candidate)
            if parsed.scheme != "file":
                return None
            path_part = unquote(parsed.path or "")
            if parsed.netloc and parsed.netloc not in {"", "localhost"}:
                path_part = f"//{parsed.netloc}{path_part}"
            candidate = path_part

        candidate = candidate.strip().strip("'").strip('"')
        if not candidate:
            return None

        path = Path(candidate).expanduser()
        try:
            if path.is_absolute():
                return path.resolve(strict=False)
            return (Path.cwd() / path).resolve(strict=False)
        except Exception:
            return None

    async def _transcribe_audio_file(self, path: Path) -> None:
        try:
            stat_result = await asyncio.to_thread(path.stat)
            size_bytes = stat_result.st_size
        except OSError as exc:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Cannot read file metadata for {path.name}: {exc}",
                    "level": "error",
                }
            )
            return

        if size_bytes > MAX_DROP_FILE_BYTES:
            max_mb = int(MAX_DROP_FILE_BYTES / (1024 * 1024))
            await self._broadcast(
                {
                    "type": "toast",
                    "message": (
                        f"Skipped {path.name}: file is too large "
                        f"({size_bytes} bytes, max {max_mb}MB)."
                    ),
                    "level": "error",
                }
            )
            return

        target_sample_rate = self.config.audio.sample_rate
        try:
            audio = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: load_audio_file(path, target_sample_rate=target_sample_rate),
            )
        except Exception as exc:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Decode failed for {path.name}: {exc}",
                    "level": "error",
                }
            )
            return

        if target_sample_rate > 0:
            duration_seconds = audio.shape[0] / float(target_sample_rate)
        else:
            duration_seconds = 0.0

        if duration_seconds > MAX_DROP_AUDIO_SECONDS:
            max_minutes = int(MAX_DROP_AUDIO_SECONDS / 60)
            await self._broadcast(
                {
                    "type": "toast",
                    "message": (
                        f"Skipped {path.name}: audio exceeds {max_minutes} minutes."
                    ),
                    "level": "error",
                }
            )
            return

        job_transcriber = self.transcriber
        job_language = self.config.model.language

        if self._transcribing_jobs == 0:
            self._busy_started_at = monotonic()
        self._transcribing_jobs += 1
        await self._set_status("transcribing", f"Transcribing {path.name}...")

        final_status, final_message = await self._process_audio(
            audio,
            transcriber=job_transcriber,
            language=job_language,
            sample_rate=target_sample_rate,
            source_label=path.name,
        )

        if final_status != "ready":
            if final_message == "Model is not loaded":
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"{path.name}: model is not loaded",
                        "level": "error",
                    }
                )
            return

        if final_message == "Ready":
            await self._broadcast({"type": "toast", "message": f"Transcribed {path.name}"})
            return

        if final_message in {"No speech detected", "No audio captured"}:
            await self._broadcast({"type": "toast", "message": f"{path.name}: {final_message}"})

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
        async with self._model_op_lock:
            await self._broadcast({"type": "toast", "message": f"Downloading {name}..."})
            loop = asyncio.get_event_loop()
            last_percent = -1

            def on_progress(percent: int) -> None:
                nonlocal last_percent
                # Keep in-flight progress below 100; reserve 100 for true completion.
                percent = max(0, min(percent, 99))
                # Throttle: only broadcast when percent actually changes.
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
                    None,
                    lambda: download_model(
                        name,
                        progress_callback=on_progress,
                        cancel_check=self._shutdown_requested.is_set,
                    ),
                )
                # Send 100% to ensure TUI sees completion
                await self._broadcast(
                    {"type": "download_progress", "model": name, "percent": 100}
                )
                await self._broadcast({"type": "toast", "message": f"Downloaded {name}"})
                # After a successful pull, make the downloaded model active.
                await self._set_selected_model(name)
                await self._broadcast_models()
            except DownloadCancelledError:
                if not self._shutdown_requested.is_set():
                    await self._broadcast(
                        {
                            "type": "toast",
                            "message": f"Download cancelled: {name}",
                            "level": "error",
                        }
                    )
            except Exception as exc:
                if not self._shutdown_requested.is_set():
                    await self._broadcast(
                        {"type": "toast", "message": f"Download failed: {exc}", "level": "error"}
                    )

    async def _remove_model(self, name: str) -> None:
        """Remove a model."""
        if not name:
            return
        async with self._model_op_lock:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: remove_model(name)
                )
                await self._broadcast({"type": "toast", "message": f"Removed {name}"})
                installed_model_names = self._installed_model_names()

                if not installed_model_names:
                    await self._enter_first_run_setup()
                    await self._broadcast(
                        {
                            "type": "toast",
                            "message": "No models installed. Download and select a model to continue.",
                        }
                    )
                elif self.config.model.name not in installed_model_names:
                    fallback_name = installed_model_names[0]
                    await self._set_selected_model(fallback_name)

                await self._broadcast_models()
            except Exception as exc:
                await self._broadcast(
                    {"type": "toast", "message": f"Remove failed: {exc}", "level": "error"}
                )

    async def _enter_first_run_setup(self) -> None:
        self._first_run_setup_required = True
        self._model_loaded = False
        if self._hotkey_started and self.hotkey:
            self.hotkey.stop()
            self._hotkey_started = False
        await self._set_status(
            "connecting",
            "First run setup required. Download and select a model in Model Manager.",
        )
        await self._broadcast_config()

    async def _set_selected_model(self, name: str) -> None:
        """Set selected model."""
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

        if get_installed_model_path(name) is None:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model {name} is not pulled. Download it before selecting.",
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
        try:
            save_config(self.config)
        except Exception as exc:
            logger.exception("Failed to persist %s config", context)
            return str(exc)
        return None

    async def _reload_transcriber(self) -> None:
        """Load a fresh transcriber from current model config and swap it in."""
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
            self._first_run_setup_required = False
            self._refresh_runtime_capabilities()
            if self._has_active_clients():
                self._start_hotkey()
            if not self._recording and self._transcribing_jobs <= 0:
                await self._set_status("ready", "Ready")

    async def _set_model_backend(self, backend_name: str) -> None:
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
                    {
                        "name": m.name,
                        "installed": m.installed,
                        "path": str(m.path) if m.path else None,
                        "size_bytes": m.size_bytes,
                        "size_estimated": m.size_estimated,
                    }
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
                {
                    "name": m.name,
                    "installed": m.installed,
                    "path": str(m.path) if m.path else None,
                    "size_bytes": m.size_bytes,
                    "size_estimated": m.size_estimated,
                }
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
        await websocket.send(json.dumps({"type": "config", "config": self._config_payload()}))

    async def _broadcast_config(self) -> None:
        """Broadcast config to all clients."""
        await self._broadcast({"type": "config", "config": self._config_payload()})

    def _config_payload(self) -> dict[str, Any]:
        self._refresh_runtime_capabilities()
        config_dict = self.config.to_dict()
        config_dict["bridge"] = {"host": "localhost", "port": 7878}
        config_dict["auto_copy"] = self._auto_copy
        config_dict["first_run_setup_required"] = self._first_run_setup_required
        config_dict["runtime"] = self._runtime_capabilities
        return config_dict

    def shutdown(self) -> None:
        """Clean up resources."""
        self._shutdown_requested.set()
        if self.recorder and self._recording:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self._recording = False
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
