"""WebSocket bridge server for TypeScript TUI communication."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import threading
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import websockets
from websockets.server import WebSocketServerProtocol

from whisper_local.audio import AudioRecorder
from whisper_local.audio_file import DEFAULT_DECODE_SAMPLE_RATE, load_audio_file
from whisper_local.config import (
    AppConfig,
    SUPPORTED_RUNTIMES,
    default_config_path,
    load_config,
    normalize_runtime_name,
    save_config,
)
from whisper_local.hotkey import HotkeyListener, parse_hotkey
from whisper_local.model_manager import (
    RUNTIME_NAMES,
    DownloadCancelledError,
    MODEL_NAMES,
    download_model,
    get_installed_model_path,
    list_installed_models,
    model_variant_format,
    prune_invalid_model_caches,
    remove_model,
)
from whisper_local.model_task_queue import SerialModelTaskQueue
from whisper_local.noise import RNNoiseSuppressor
from whisper_local.output import (
    append_to_file,
    capture_clipboard_snapshot,
    copy_to_clipboard,
    paste_from_clipboard,
    restore_clipboard_snapshot,
)
from whisper_local.vad import VadProcessor

logger = logging.getLogger(__name__)

WHISPER_CPP_BINARIES = ("whisper-cli", "whisper-cpp", "main")
MAX_DROP_FILES = 32
MAX_DROP_FILE_BYTES = 512 * 1024 * 1024
MAX_DROP_AUDIO_SECONDS = 4 * 60 * 60
AUTO_PASTE_INPUT_SUPPRESS_MS = 1000
AUTO_REVERT_CLIPBOARD_DELAY_MS = 120


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
    """WebSocket server bridging the TypeScript TUI to Python runtime."""

    def __init__(self, config: AppConfig) -> None:
        """
        Initialize the BridgeServer internal runtime state and placeholders from the given configuration.

        Sets up client sets, recording/state flags, concurrency primitives (locks and events), background and per-model task registries, runtime capability caching, and lazy placeholders for audio/transcription/hotkey components. If the provided config enables auto_paste while auto_copy is disabled, auto_copy will be enabled on the server and the config will be updated accordingly.

        Parameters:
            config (AppConfig): Application configuration used to initialize server settings and defaults.
        """
        self.config = config
        self.clients: set[WebSocketServerProtocol] = set()
        self._passive_clients: set[WebSocketServerProtocol] = set()
        self._recording = False
        self._auto_copy = bool(config.auto_copy)
        self._auto_paste = bool(config.auto_paste)
        self._auto_revert_clipboard = bool(getattr(config, "auto_revert_clipboard", True))
        if self._auto_paste and not self._auto_copy:
            self._auto_copy = True
            self.config.auto_copy = True
            save_config(self.config)
            logger.info("Auto paste enabled in config; forcing auto copy on")
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
        self._clipboard_output_lock = asyncio.Lock()
        self._runtime_capabilities: dict[str, Any] = {}
        self._runtime_capabilities_updated_at = 0.0
        self._runtime_capabilities_dirty = True
        self._shutdown_requested = threading.Event()

        self._background_tasks: set[asyncio.Task] = set()
        self._model_tasks: dict[str, asyncio.Task] = {}
        self._download_queue = SerialModelTaskQueue()

        # Audio/transcription components (initialized lazily)
        self.recorder: AudioRecorder | None = None
        self.noise: RNNoiseSuppressor | None = None
        self.vad: VadProcessor | None = None
        self.transcriber: Any | None = None
        self.hotkey: HotkeyListener | None = None

    def _spawn_task(self, coro) -> asyncio.Task:
        """Create a background task and prevent it from being garbage-collected."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task) -> None:
        """Clean up a finished background task and surface any unhandled exception."""
        self._background_tasks.discard(task)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                logger.error("Background task failed: %s", exc)

    def _spawn_model_task(self, name: str, coro) -> asyncio.Task:
        """
        Start and track a background task for a named model operation.

        If a previous task with the same name is running, cancel it and replace it with a new task. The mapping for the name is removed when the task completes.

        Parameters:
            coro: The coroutine to schedule as the model task.

        Returns:
            asyncio.Task: The created task running the provided coroutine.
        """
        existing = self._model_tasks.get(name)
        if existing is not None and not existing.done():
            existing.cancel()
        task = self._spawn_task(coro)
        self._model_tasks[name] = task

        def _cleanup(_t: asyncio.Task) -> None:
            """
            Remove the tracked model task entry when the completed task matches the recorded task for that model.

            Parameters:
                _t (asyncio.Task): The completed task; if it is the same object as the currently stored task for the associated model name, the task entry is removed.
            """
            if self._model_tasks.get(name) is _t:
                self._model_tasks.pop(name, None)

        task.add_done_callback(_cleanup)
        return task

    @staticmethod
    def _download_task_key(name: str, runtime: str) -> str:
        return f"{runtime}:{name}"

    def _resolve_download_cancel_key(self, name: str, runtime: str | None) -> str | None:
        model_name = str(name or "").strip()
        runtime_name = str(runtime or "").strip()

        if not model_name:
            return self._download_queue.resolve_single_candidate()

        if ":" in model_name:
            return model_name

        if runtime_name:
            return self._download_task_key(model_name, normalize_runtime_name(runtime_name))

        matches = self._download_queue.keys_matching(model_name)
        if len(matches) == 1:
            return matches[0]
        return None

    def _client_path(self, websocket: WebSocketServerProtocol) -> str:
        """
        Resolve the connection path for a client WebSocket across different websockets library versions.

        Returns:
            str: The connection path string, or an empty string if it cannot be determined.
        """
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

    def _installed_model_names(self, runtime: str | None = None) -> list[str]:
        target_runtime = normalize_runtime_name(runtime or self.config.model.runtime)
        installed: list[str] = []
        for model in list_installed_models():
            variants = getattr(model, "variants", None)
            if isinstance(variants, dict):
                variant = variants.get(target_runtime)
                if variant and getattr(variant, "installed", False):
                    installed.append(model.name)
                continue
            if bool(getattr(model, "installed", False)):
                installed.append(model.name)
        return installed

    def _has_installed_models(self, runtime: str | None = None) -> bool:
        return bool(self._installed_model_names(runtime=runtime))

    async def start(
        self,
        host: str = "localhost",
        port: int = 7878,
        capture_logs: bool = False,
    ) -> None:
        """
        Start the bridge WebSocket server, initialize runtime components, and begin model loading.

        Binds to the given host and port, initializes audio/transcription components and runtime state, prunes model caches, determines whether first-run setup is required, and either sets the first-run status or triggers asynchronous model loading. Runs until the server is shut down.

        Parameters:
            host (str): Hostname or IP address to bind the WebSocket server to.
            port (int): TCP port to listen on for incoming WebSocket connections.
            capture_logs (bool): If true, install a WebSocket log handler to forward log records to connected clients.
        """
        self._loop = asyncio.get_event_loop()

        self._ensure_whisper_cpp_installed()

        if capture_logs:
            self._install_log_handler()

        async with websockets.serve(self._handle_client, host, port):
            logger.info(f"Bridge server running on ws://{host}:{port}")
            self._spawn_task(self._initialize_runtime_after_server_start())
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
        """Initialize audio, preprocessing, and hotkey components."""
        self.recorder = AudioRecorder(sample_rate=self.config.audio.sample_rate)
        self.noise = RNNoiseSuppressor(enabled=self.config.audio.noise_suppression.enabled)
        self.vad = VadProcessor(
            enabled=self.config.vad.enabled, aggressiveness=self.config.vad.aggressiveness
        )
        self.hotkey = HotkeyListener(
            self.config.hotkey.key,
            on_press=self._handle_hotkey_press,
            on_release=self._handle_hotkey_release,
        )

    def _create_transcriber(self) -> Any:
        from whisper_local.transcribe import Transcriber

        return Transcriber(
            model_name=self.config.model.name,
            runtime=self.config.model.runtime,
            device=self.config.model.device,
            compute_type=self.config.model.compute_type,
            model_path=self.config.model.path,
        )

    def _ensure_whisper_cpp_installed(self) -> None:
        for binary in WHISPER_CPP_BINARIES:
            if shutil.which(binary) is not None:
                return
        raise RuntimeError(
            "whisper.cpp is required but not installed. Install with: brew install whisper-cpp"
        )

    def _detect_runtime_capabilities(self, selected_runtime: str | None = None) -> dict[str, Any]:
        from whisper_local.transcribe import detect_runtime_capabilities

        return detect_runtime_capabilities(selected_runtime or self.config.model.runtime)

    _RUNTIME_CAPS_TTL = 30.0

    def _refresh_runtime_capabilities(self, *, force: bool = False) -> None:
        now = monotonic()
        if not force and not self._runtime_capabilities_dirty:
            if (now - self._runtime_capabilities_updated_at) < self._RUNTIME_CAPS_TTL:
                return
        self._runtime_capabilities = self._detect_runtime_capabilities()
        self._runtime_capabilities_updated_at = now
        self._runtime_capabilities_dirty = False

    def _invalidate_runtime_capabilities(self) -> None:
        self._runtime_capabilities_dirty = True

    def _set_runtime_capabilities(self, capabilities: dict[str, Any]) -> None:
        self._runtime_capabilities = capabilities
        self._runtime_capabilities_updated_at = monotonic()
        self._runtime_capabilities_dirty = False

    async def _initialize_runtime_after_server_start(self) -> None:
        loop = asyncio.get_event_loop()

        try:
            await loop.run_in_executor(None, self._init_components)
        except Exception as exc:
            logger.exception("Bridge component initialization failed")
            await self._set_status("error", f"Startup failed: {exc}")
            return

        try:
            await loop.run_in_executor(None, prune_invalid_model_caches)
        except Exception:
            logger.warning("Failed to prune invalid model cache entries", exc_info=True)

        self._first_run_setup_required = not self._has_installed_models()

        try:
            runtime_capabilities = await loop.run_in_executor(
                None,
                self._detect_runtime_capabilities,
                self.config.model.runtime,
            )
            self._set_runtime_capabilities(runtime_capabilities)
        except Exception:
            logger.warning("Failed to detect runtime capabilities", exc_info=True)

        await self._broadcast_config()

        if self._first_run_setup_required:
            await self._set_status(
                "connecting",
                "First run setup required. Download and select a model in Model Manager.",
            )
            return

        selected_installed = get_installed_model_path(
            self.config.model.name, runtime=self.config.model.runtime
        )
        if selected_installed is None:
            installed_names = self._installed_model_names(runtime=self.config.model.runtime)
            if not installed_names:
                self._first_run_setup_required = True
                await self._set_status(
                    "connecting",
                    "First run setup required. Download and select a model in Model Manager.",
                )
                await self._broadcast_config()
                return
            self.config.model.name = installed_names[0]
            self.config.model.path = None
            persist_error = self._persist_config("fallback selected model")
            await self._broadcast(
                {
                    "type": "toast",
                    "message": (
                        f"Selected model unavailable for runtime {self.config.model.runtime}. "
                        f"Using {self.config.model.name}."
                    ),
                    "level": "info",
                }
            )
            if persist_error:
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Failed to persist fallback model: {persist_error}",
                        "level": "error",
                    }
                )
            await self._broadcast_config()

        await self._load_model_async()

    async def _load_model_async(self) -> None:
        """Load the transcription model asynchronously."""
        await self._set_status(
            "downloading",
            f"Loading {self.config.model.runtime} model {self.config.model.name}...",
        )
        try:
            transcriber = self.transcriber
            if transcriber is None:
                transcriber = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._create_transcriber,
                )
                self.transcriber = transcriber
            if transcriber is None:
                raise RuntimeError("Transcriber is not initialized")

            await asyncio.get_event_loop().run_in_executor(None, transcriber.load)
            self._model_loaded = True
            self._start_hotkey()
            info = transcriber.runtime_info()
            logger.info(
                "Transcriber ready runtime=%s model=%s device=%s compute_type=%s source=%s",
                info.get("runtime", "unknown"),
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
        transcriber: Any | None = None,
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
            copied_to_clipboard = True
            if self.config.output.clipboard or self._auto_copy or self._auto_paste:
                async with self._clipboard_output_lock:
                    should_revert_clipboard = self._auto_paste and self._auto_revert_clipboard
                    clipboard_snapshot = None
                    if should_revert_clipboard:
                        clipboard_snapshot = await asyncio.to_thread(capture_clipboard_snapshot)

                    copied_to_clipboard = copy_to_clipboard(result.text)
                    if self._auto_paste and copied_to_clipboard:
                        await self._broadcast(
                            {"type": "suppress_paste_input", "duration_ms": AUTO_PASTE_INPUT_SUPPRESS_MS}
                        )
                        pasted = await asyncio.to_thread(paste_from_clipboard)
                        if should_revert_clipboard:
                            if pasted:
                                await asyncio.sleep(AUTO_REVERT_CLIPBOARD_DELAY_MS / 1000)
                            await asyncio.to_thread(restore_clipboard_snapshot, clipboard_snapshot)
                    elif should_revert_clipboard:
                        await asyncio.to_thread(restore_clipboard_snapshot, clipboard_snapshot)
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
            runtime_info = job_transcriber.runtime_info()

            logger.info(
                "bench runtime=%s model_size=%s device=%s compute_type=%s input_ms=%d post_noise_ms=%d post_ms=%d "
                "noise(enabled=%s,available=%s,applied=%s,runtime=%s) "
                "vad(enabled=%s,available=%s,applied=%s) preprocess_ms=%d transcribe_ms=%d total_ms=%d rtf=%.3f "
                "language(requested=%s,detected=%s)",
                runtime_info.get("runtime", self.config.model.runtime),
                runtime_info.get("model_name", self.config.model.name),
                runtime_info.get("effective_device", self.config.model.device),
                runtime_info.get("effective_compute_type", self.config.model.compute_type),
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

    def _mirror_toast_to_logger(self, message: dict[str, Any]) -> None:
        """Mirror backend toast events to logger with optional toast metadata."""
        if message.get("type") != "toast":
            return
        text = message.get("message")
        if not isinstance(text, str) or not text.strip():
            return

        level = str(message.get("level") or "info").lower()
        metadata_parts: list[str] = []
        for key in ("action", "runtime", "model"):
            value = message.get(key)
            if value is None:
                continue
            as_text = str(value).strip()
            if as_text:
                metadata_parts.append(f"{key}={as_text}")
        suffix = f" ({', '.join(metadata_parts)})" if metadata_parts else ""

        if level == "error":
            logger.error("toast: %s%s", text, suffix)
            return
        logger.info("toast: %s%s", text, suffix)

    async def _broadcast(self, message: dict[str, Any]) -> None:
        """Send message to all connected clients."""
        self._mirror_toast_to_logger(message)
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
        """
        Dispatch a JSON-encoded control message from a client to the appropriate bridge handler.

        Parses the provided message and routes it by the top-level "type" field to perform actions such as recording control, model management (download, cancel, remove, select), runtime/device/compute configuration, audio/VAD/noise toggles, hotkey and theme updates, clipboard/file output changes, requests for model/config data, and initiating transcription from pasted text or files. Direct replies are sent to the given websocket when required; other responses are broadcast to connected clients. Invalid JSON or unknown message types are ignored.

        Parameters:
            websocket (WebSocketServerProtocol): The client's WebSocket connection used for direct replies when applicable.
            message (str): A JSON-encoded message string that must include a top-level "type" field and any type-specific payload.
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
                requested_auto_copy = bool(data.get("enabled", not self._auto_copy))
                if not requested_auto_copy and self._auto_paste:
                    logger.info(
                        "Rejected auto copy disable request because auto paste is enabled"
                    )
                    await self._broadcast(
                        {
                            "type": "toast",
                            "message": "Auto copy remains on while auto paste is enabled",
                            "level": "info",
                        }
                    )
                    await self._broadcast_config()
                    return

                self._auto_copy = requested_auto_copy
                self.config.auto_copy = self._auto_copy
                persist_error: str | None = None
                try:
                    save_config(self.config)
                except Exception as exc:
                    logger.exception("Failed to persist auto copy config")
                    persist_error = str(exc)
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Auto copy {'on' if self._auto_copy else 'off'}",
                        "level": "success",
                    }
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
            elif msg_type == "toggle_auto_paste":
                self._auto_paste = bool(data.get("enabled", not self._auto_paste))
                self.config.auto_paste = self._auto_paste
                auto_copy_forced = False
                if self._auto_paste and not self._auto_copy:
                    self._auto_copy = True
                    self.config.auto_copy = True
                    auto_copy_forced = True
                    logger.info("Auto paste enabled; forcing auto copy on")
                persist_error = None
                try:
                    save_config(self.config)
                except Exception as exc:
                    logger.exception("Failed to persist auto paste config")
                    persist_error = str(exc)
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": (
                            "Auto paste on; auto copy on"
                            if auto_copy_forced
                            else f"Auto paste {'on' if self._auto_paste else 'off'}"
                        ),
                        "level": "success",
                    }
                )
                if persist_error:
                    await self._broadcast(
                        {
                            "type": "toast",
                            "message": f"Auto paste updated for this session, but failed to save: {persist_error}",
                            "level": "error",
                        }
                    )
                await self._broadcast_config()
            elif msg_type == "toggle_auto_revert_clipboard":
                self._auto_revert_clipboard = bool(
                    data.get("enabled", not self._auto_revert_clipboard)
                )
                self.config.auto_revert_clipboard = self._auto_revert_clipboard
                persist_error = None
                try:
                    save_config(self.config)
                except Exception as exc:
                    logger.exception("Failed to persist auto revert clipboard config")
                    persist_error = str(exc)
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": (
                            f"Auto revert clipboard {'on' if self._auto_revert_clipboard else 'off'}"
                        ),
                        "level": "success",
                    }
                )
                if persist_error:
                    await self._broadcast(
                        {
                            "type": "toast",
                            "message": (
                                "Auto revert clipboard updated for this session, but failed to save: "
                                f"{persist_error}"
                            ),
                            "level": "error",
                        }
                    )
                await self._broadcast_config()
            elif msg_type == "set_hotkey_blocked":
                self._hotkey_blocked = bool(data.get("enabled", False))
            elif msg_type == "set_hotkey_mode":
                await self._set_hotkey_mode(data.get("mode", ""))
            elif msg_type == "set_theme":
                await self._set_theme(data.get("theme", ""))
            elif msg_type == "set_audio_sample_rate":
                await self._set_audio_sample_rate(data.get("sample_rate"))
            elif msg_type == "set_vad_aggressiveness":
                await self._set_vad_aggressiveness(data.get("aggressiveness"))
            elif msg_type == "set_output_clipboard":
                await self._set_output_clipboard(data.get("enabled"))
            elif msg_type == "set_output_file_enabled":
                await self._set_output_file_enabled(data.get("enabled"))
            elif msg_type == "set_output_file_path":
                await self._set_output_file_path(data.get("path", ""))
            elif msg_type == "set_model_path":
                await self._set_model_path(data.get("path"))
            elif msg_type == "set_model_runtime":
                await self._set_model_runtime(data.get("runtime", ""))
            elif msg_type == "set_model_device":
                await self._set_model_device(data.get("device", ""))
            elif msg_type == "set_model_compute_type":
                await self._set_model_compute_type(data.get("compute_type", ""))
            elif msg_type == "set_model_language":
                await self._set_model_language(data.get("language"))
            elif msg_type == "download_model":
                name = data.get("name", "")
                if not name:
                    return
                runtime = normalize_runtime_name(data.get("runtime", self.config.model.runtime))
                activate_runtime = data.get("activate_runtime")
                activate_target = (
                    normalize_runtime_name(activate_runtime)
                    if isinstance(activate_runtime, str) and activate_runtime.strip()
                    else None
                )
                download_key = self._download_task_key(name, runtime)
                self._download_queue.enqueue_download(download_key, model=name, runtime=runtime)
                task = self._spawn_model_task(
                    download_key,
                    self._download_model(name, runtime=runtime, activate_runtime=activate_target),
                )
                self._download_queue.bind_task(download_key, task)
            elif msg_type == "cancel_model_download":
                await self._cancel_model_download(
                    data.get("name", ""),
                    runtime=data.get("runtime"),
                )
            elif msg_type == "cancel_all_model_downloads":
                await self._cancel_all_model_downloads()
            elif msg_type == "remove_model":
                name = data.get("name", "")
                runtime = normalize_runtime_name(data.get("runtime", self.config.model.runtime))
                self._spawn_model_task(
                    f"remove:{runtime}:{name}",
                    self._remove_model(name, runtime=runtime),
                )
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
                    if copy_to_clipboard(text):
                        await self._broadcast(
                            {
                                "type": "toast",
                                "message": "Copied to clipboard",
                                "level": "success",
                            }
                        )
                    else:
                        await self._broadcast(
                            {
                                "type": "toast",
                                "message": "Clipboard copy failed",
                                "level": "error",
                            }
                        )
            elif msg_type == "get_config_file":
                await self._send_config_file(websocket)
            elif msg_type == "set_welcome_shown":
                await self._set_welcome_shown()
            elif msg_type == "get_capabilities":
                await self._send_capabilities(websocket)
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

            if not await asyncio.to_thread(path.exists):
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"File not found: {path}",
                        "level": "error",
                    }
                )
                continue
            if not await asyncio.to_thread(path.is_file):
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Not a file: {path}",
                        "level": "error",
                    }
                )
                continue
            if not await asyncio.to_thread(os.access, path, os.R_OK):
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Cannot read file: {path}",
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
                {
                    "type": "toast",
                    "message": f"Queued file transcription: {valid_paths[0].name}",
                    "level": "success",
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Queued {len(valid_paths)} files for transcription",
                    "level": "success",
                }
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
        """Normalize pasted file paths without sandboxing to home/cwd.

        We resolve symlinks and relative segments for safety, but keep this
        permissive so mounted volumes and network shares are accepted.
        """
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
            base_path = path if path.is_absolute() else Path.cwd() / path
            resolved = base_path.resolve(strict=False)
            if not resolved.is_absolute():
                return None
            return resolved
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
        effective_sample_rate = (
            target_sample_rate if target_sample_rate > 0 else DEFAULT_DECODE_SAMPLE_RATE
        )
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

        duration_seconds = audio.shape[0] / float(effective_sample_rate)

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
            sample_rate=effective_sample_rate,
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
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Transcribed {path.name}",
                    "level": "success",
                }
            )
            return

        if final_message in {"No speech detected", "No audio captured"}:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"{path.name}: {final_message}",
                    "level": "info",
                }
            )

    async def _toggle_noise(self, enabled: bool) -> None:
        """Toggle noise suppression."""
        self.config.audio.noise_suppression.enabled = enabled
        self.noise = RNNoiseSuppressor(enabled=enabled)
        save_config(self.config)
        state = "on" if enabled else "off"
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Noise suppression {state}",
                "level": "success",
            }
        )
        await self._broadcast_config()

    async def _toggle_vad(self, enabled: bool) -> None:
        """
        Enable or disable voice activity detection (VAD) and persist the change.

        Parameters:
            enabled (bool): `True` to enable VAD, `False` to disable it.

        Notes:
            This updates the in-memory VAD processor, saves the configuration, and notifies connected clients with a toast and an updated config broadcast.
        """
        self.config.vad.enabled = enabled
        self.vad = VadProcessor(
            enabled=enabled, aggressiveness=self.config.vad.aggressiveness
        )
        save_config(self.config)
        state = "on" if enabled else "off"
        await self._broadcast({"type": "toast", "message": f"VAD {state}", "level": "success"})
        await self._broadcast_config()

    async def _download_model(
        self,
        name: str,
        runtime: str | None = None,
        activate_runtime: str | None = None,
    ) -> None:
        """
        Download and activate a model while broadcasting progress and status updates to connected clients.

        This method pulls the specified model, broadcasts incremental download progress (0–100) and toast messages for start, completion, cancellation, or failure, and on success sets the downloaded model as the selected model and refreshes the model list. The download is cooperatively cancellable via the server's per-model cancel event and respects the server shutdown signal.

        Parameters:
            name (str): Name of the model to download.
        """
        if not name:
            return
        normalized_runtime = normalize_runtime_name(runtime or self.config.model.runtime)
        activate_runtime_name = (
            normalize_runtime_name(activate_runtime)
            if activate_runtime
            else None
        )
        download_key = self._download_task_key(name, normalized_runtime)
        cancel_event = self._download_queue.cancel_event_for(download_key)
        if cancel_event is None:
            cancel_event = self._download_queue.enqueue_download(
                download_key,
                model=name,
                runtime=normalized_runtime,
            )
        if cancel_event.is_set():
            self._download_queue.mark_cancelled(download_key)
            return

        async with self._model_op_lock:
            self._download_queue.mark_running(download_key)
            if cancel_event.is_set():
                self._download_queue.mark_cancelled(download_key)
                return
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Downloading {name} ({normalized_runtime})...",
                    "level": "info",
                }
            )
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
                        {
                            "type": "download_progress",
                            "model": name,
                            "runtime": normalized_runtime,
                            "percent": percent,
                        }
                    ),
                    loop,
                )

            try:
                await loop.run_in_executor(
                    None,
                    lambda: download_model(
                        name,
                        runtime=normalized_runtime,
                        progress_callback=on_progress,
                        cancel_check=lambda: self._shutdown_requested.is_set() or cancel_event.is_set(),
                    ),
                )
                self._download_queue.mark_completed(download_key)
                # Send 100% to ensure TUI sees completion
                await self._broadcast(
                    {
                        "type": "download_progress",
                        "model": name,
                        "runtime": normalized_runtime,
                        "percent": 100,
                    }
                )
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Downloaded {name} ({normalized_runtime})",
                        "model": name,
                        "runtime": normalized_runtime,
                        "action": "download_complete",
                        "level": "success",
                    }
                )
                if activate_runtime_name:
                    self.config.model.name = name
                    self.config.model.path = None
                    persist_error = self._persist_config("model selection for runtime activation")
                    if persist_error:
                        await self._broadcast(
                            {
                                "type": "toast",
                                "message": (
                                    "Downloaded model, but failed to persist selection: "
                                    f"{persist_error}"
                                ),
                                "level": "error",
                            }
                        )
                    await self._set_model_runtime(
                        activate_runtime_name, allow_missing_variant_prompt=False
                    )
                elif normalized_runtime == self.config.model.runtime:
                    # After a successful pull for the active runtime, make it active.
                    await self._set_selected_model(name)
                await self._broadcast_models()
            except DownloadCancelledError:
                self._download_queue.mark_cancelled(download_key)
                if not self._shutdown_requested.is_set():
                    await self._broadcast(
                        {
                            "type": "toast",
                            "message": f"Download cancelled: {name} ({normalized_runtime})",
                            "model": name,
                            "runtime": normalized_runtime,
                            "action": "download_cancelled",
                            "level": "info",
                        }
                    )
                    await self._broadcast_models()
            except asyncio.CancelledError:
                cancel_event.set()
                self._download_queue.mark_cancelled(download_key)
                raise
            except Exception as exc:
                if cancel_event.is_set():
                    self._download_queue.mark_cancelled(download_key)
                else:
                    self._download_queue.mark_failed(download_key)
                if not self._shutdown_requested.is_set():
                    await self._broadcast(
                        {
                            "type": "toast",
                            "message": f"Download failed: {exc}",
                            "model": name,
                            "runtime": normalized_runtime,
                            "level": "error",
                            "action": "download_failed",
                        }
                    )
                    await self._broadcast_models()

    async def _cancel_model_download(self, name: str, runtime: Any = None) -> None:
        """
        Request cancellation of an in-progress model download.

        If `name` is empty and exactly one download is active or queued, that download will be cancelled.
        If no active download matches `name`, an error toast with message
        "No active download matches request" is broadcast to clients.
        If a cancellation is already in progress for the named model, this is a no-op.
        Otherwise the method signals cancellation for the model and broadcasts a toast indicating the cancellation.

        Parameters:
            name (str): The model name to cancel; may be an empty string to infer a single active download.
        """
        no_active_download_message = "No active download matches request"
        resolved_key = self._resolve_download_cancel_key(str(name or ""), runtime=str(runtime or ""))
        if resolved_key is None:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": no_active_download_message,
                    "level": "error",
                }
            )
            return

        result = self._download_queue.cancel(resolved_key)
        snapshot = result.task
        if snapshot is None:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": no_active_download_message,
                    "level": "error",
                }
            )
            return

        if result.status == "active":
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Cancelling download {snapshot.model}...",
                    "model": snapshot.model,
                    "runtime": snapshot.runtime,
                    "level": "info",
                }
            )
            return

        if result.status == "queued":
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Cancelled queued download {snapshot.model}.",
                    "model": snapshot.model,
                    "runtime": snapshot.runtime,
                    "action": "download_cancelled",
                    "level": "info",
                }
            )
            return

        if result.status in {"already_cancelling", "already_cancelled"}:
            return

        await self._broadcast(
            {
                "type": "toast",
                "message": no_active_download_message,
                "level": "error",
            }
        )

    async def _cancel_all_model_downloads(self) -> None:
        results = self._download_queue.cancel_all()
        for result in results:
            snapshot = result.task
            if snapshot is None:
                continue
            if result.status == "queued":
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Cancelled queued download {snapshot.model}.",
                        "model": snapshot.model,
                        "runtime": snapshot.runtime,
                        "action": "download_cancelled",
                        "level": "info",
                    }
                )
                continue
            if result.status == "active":
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Cancelling download {snapshot.model}...",
                        "model": snapshot.model,
                        "runtime": snapshot.runtime,
                        "level": "info",
                    }
                )

    async def _remove_model(self, name: str, runtime: str | None = None) -> None:
        """
        Remove the installed model identified by `name` and notify connected clients of the outcome.

        If removal succeeds, broadcasts a success toast, refreshes the installed model list, enters first-run setup and notifies clients if no models remain, or selects a fallback model if the removed model was the current selection. On failure, broadcasts an error toast describing the failure.

        Parameters:
            name (str): The name of the model to remove. If empty, no action is taken.
        """
        if not name:
            return
        normalized_runtime = normalize_runtime_name(runtime or self.config.model.runtime)
        async with self._model_op_lock:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: remove_model(name, runtime=normalized_runtime),
                )
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Removed {name} ({normalized_runtime})",
                        "model": name,
                        "runtime": normalized_runtime,
                        "action": "remove_complete",
                        "level": "success",
                    }
                )
                installed_model_names = self._installed_model_names(
                    runtime=self.config.model.runtime
                )

                if not installed_model_names:
                    await self._enter_first_run_setup()
                    await self._broadcast(
                        {
                            "type": "toast",
                            "message": "No models installed. Download and select a model to continue.",
                            "level": "info",
                        }
                    )
                elif self.config.model.name not in installed_model_names:
                    fallback_name = installed_model_names[0]
                    await self._set_selected_model(fallback_name)

                await self._broadcast_models()
            except Exception as exc:
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": f"Remove failed: {exc}",
                        "model": name,
                        "runtime": normalized_runtime,
                        "level": "error",
                        "action": "remove_failed",
                    }
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

        if get_installed_model_path(name, runtime=self.config.model.runtime) is None:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": (
                        f"Model {name} is not pulled for runtime "
                        f"{self.config.model.runtime}. Download it before selecting."
                    ),
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
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Selected model set to {name}",
                "level": "success",
            }
        )
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
        """Load a fresh transcriber from current model config and swap it in.

        In-flight transcriptions capture their transcriber reference before
        this swap occurs, so they complete with the previous model. New
        recordings will use the updated transcriber.
        """
        async with self._model_reload_lock:
            next_transcriber = await asyncio.get_event_loop().run_in_executor(
                None,
                self._create_transcriber,
            )
            await asyncio.get_event_loop().run_in_executor(None, next_transcriber.load)
            self.transcriber = next_transcriber
            self._model_loaded = True
            self._first_run_setup_required = False
            self._refresh_runtime_capabilities(force=True)
            if self._has_active_clients():
                self._start_hotkey()
            if not self._recording and self._transcribing_jobs <= 0:
                await self._set_status("ready", "Ready")

    async def _set_model_runtime(
        self,
        runtime_name: str,
        allow_missing_variant_prompt: bool = True,
    ) -> None:
        normalized = normalize_runtime_name(runtime_name)
        if normalized not in SUPPORTED_RUNTIMES:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Invalid model runtime: {runtime_name}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        capabilities = self._detect_runtime_capabilities(normalized)
        runtime_options = capabilities.get("model", {}).get("runtimes", {})
        runtime_state = runtime_options.get(normalized, {"enabled": False, "reason": "Unsupported"})
        if not runtime_state.get("enabled", False):
            await self._broadcast(
                {
                    "type": "toast",
                    "message": (
                        f"Runtime {normalized} unavailable: "
                        f"{runtime_state.get('reason', 'unsupported')}"
                    ),
                    "level": "error",
                }
            )
            self._set_runtime_capabilities(capabilities)
            await self._broadcast_config()
            return

        if self.config.model.runtime == normalized:
            self._set_runtime_capabilities(capabilities)
            await self._broadcast_config()
            return

        selected_model = self.config.model.name
        selected_variant_path = get_installed_model_path(selected_model, runtime=normalized)
        if selected_variant_path is None and not self._first_run_setup_required:
            if allow_missing_variant_prompt:
                await self._broadcast(
                    {
                        "type": "runtime_switch_requires_model_variant",
                        "runtime": normalized,
                        "model": selected_model,
                        "format": model_variant_format(normalized),
                    }
                )
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": (
                            f"Switching to {normalized} requires downloading "
                            f"{selected_model} ({model_variant_format(normalized)})."
                        ),
                        "level": "info",
                    }
                )
                self._set_runtime_capabilities(capabilities)
                await self._broadcast_config()
                return
            await self._broadcast(
                {
                    "type": "toast",
                    "message": (
                        f"Runtime {normalized} requires model files for {selected_model}. "
                        "Download the model variant first."
                    ),
                    "level": "error",
                    }
                )
            self._set_runtime_capabilities(capabilities)
            await self._broadcast_config()
            return

        previous_runtime = self.config.model.runtime
        previous_device = self.config.model.device
        previous_compute_type = self.config.model.compute_type
        self.config.model.runtime = normalized
        self._set_runtime_capabilities(capabilities)

        normalized_device, normalized_compute_type = self._normalize_model_runtime_for_runtime(
            capabilities,
            device=self.config.model.device,
            compute_type=self.config.model.compute_type,
        )
        self.config.model.device = normalized_device
        self.config.model.compute_type = normalized_compute_type

        persist_error = self._persist_config("model runtime")

        if self._first_run_setup_required:
            await self._broadcast_config()
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model runtime {normalized}",
                    "level": "success",
                }
            )
            if persist_error:
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": (
                            f"Model runtime applied, but failed to save: {persist_error}"
                        ),
                        "level": "error",
                    }
                )
            return

        try:
            await self._reload_transcriber()
        except Exception as exc:
            logger.exception("Failed to apply model runtime")
            self.config.model.runtime = previous_runtime
            self.config.model.device = previous_device
            self.config.model.compute_type = previous_compute_type
            self._set_runtime_capabilities(self._detect_runtime_capabilities(previous_runtime))
            rollback_error = self._persist_config("model runtime rollback")
            await self._broadcast_config()
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Failed to apply model runtime: {exc}",
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
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Model runtime {normalized}",
                "level": "success",
            }
        )
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model runtime applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    def _normalize_model_runtime_for_runtime(
        self,
        capabilities: dict[str, Any],
        *,
        device: str,
        compute_type: str,
    ) -> tuple[str, str]:
        runtime_model = capabilities.get("model", {})
        runtime_devices = runtime_model.get("devices", {})
        normalized_device = str(device).strip().lower() or "cpu"
        normalized_compute_type = str(compute_type).strip().lower() or "int8"

        current_device_state = runtime_devices.get(normalized_device, {"enabled": False})
        if not current_device_state.get("enabled", False):
            for candidate in ("cuda", "mps", "cpu"):
                candidate_state = runtime_devices.get(candidate, {"enabled": False})
                if candidate_state.get("enabled", False):
                    normalized_device = candidate
                    break
        compute_map = runtime_model.get("compute_types_by_device", {})
        valid_compute_types = {
            str(item).strip().lower()
            for item in compute_map.get(normalized_device, [])
            if str(item).strip()
        }
        if valid_compute_types and normalized_compute_type not in valid_compute_types:
            for candidate in (
                "int8",
                "default",
                "int8_float32",
                "float32",
                "float16",
                "int8_float16",
            ):
                if candidate in valid_compute_types:
                    normalized_compute_type = candidate
                    break
            else:
                normalized_compute_type = sorted(valid_compute_types)[0]

        return normalized_device, normalized_compute_type

    async def _set_model_device(self, device: str) -> None:
        self._refresh_runtime_capabilities(force=True)
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

        if self._first_run_setup_required:
            await self._broadcast_config()
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model device {normalized}",
                    "level": "success",
                }
            )
            if persist_error:
                await self._broadcast(
                    {
                        "type": "toast",
                        "message": (
                            f"Model device applied, but failed to save: {persist_error}"
                        ),
                        "level": "error",
                    }
                )
            return

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
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Model device {normalized}",
                "level": "success",
            }
        )
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model device applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_model_compute_type(self, compute_type: str) -> None:
        self._refresh_runtime_capabilities(force=True)
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
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Compute type {normalized}",
                "level": "success",
            }
        )
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
                "level": "success",
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

    async def _set_audio_sample_rate(self, sample_rate: Any) -> None:
        try:
            normalized = int(sample_rate)
        except (TypeError, ValueError):
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Invalid sample rate: {sample_rate}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        allowed = {8000, 16000, 32000, 48000}
        if normalized not in allowed:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Unsupported sample rate: {normalized}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        if self._recording:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": "Cannot change sample rate while recording",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        if self.config.audio.sample_rate == normalized:
            return

        self.config.audio.sample_rate = normalized
        if self.recorder:
            self.recorder.sample_rate = normalized
        persist_error = self._persist_config("audio sample rate")

        await self._broadcast_config()
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Sample rate {normalized} Hz",
                "level": "success",
            }
        )
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Sample rate applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_vad_aggressiveness(self, aggressiveness: Any) -> None:
        try:
            normalized = int(aggressiveness)
        except (TypeError, ValueError):
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Invalid VAD aggressiveness: {aggressiveness}",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        if normalized < 0 or normalized > 3:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": "VAD aggressiveness must be between 0 and 3",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        if self.config.vad.aggressiveness == normalized:
            return

        previous_aggressiveness = self.config.vad.aggressiveness
        previous_vad = self.vad
        self.config.vad.aggressiveness = normalized

        try:
            self.vad = VadProcessor(
                enabled=self.config.vad.enabled, aggressiveness=self.config.vad.aggressiveness
            )
        except Exception as exc:
            logger.exception("Failed to apply VAD aggressiveness")
            self.config.vad.aggressiveness = previous_aggressiveness
            self.vad = previous_vad
            rollback_error = self._persist_config("vad aggressiveness rollback")
            await self._broadcast_config()
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Failed to apply VAD aggressiveness: {exc}",
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

        persist_error = self._persist_config("vad aggressiveness")
        await self._broadcast_config()
        await self._broadcast(
            {
                "type": "toast",
                "message": f"VAD aggressiveness {self.config.vad.aggressiveness}",
                "level": "success",
            }
        )
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"VAD aggressiveness applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_output_clipboard(self, enabled: Any) -> None:
        normalized = bool(enabled)
        if self.config.output.clipboard == normalized:
            return

        self.config.output.clipboard = normalized
        persist_error = self._persist_config("output clipboard")
        await self._broadcast_config()
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Clipboard output {'on' if normalized else 'off'}",
                "level": "success",
            }
        )
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Clipboard output applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_output_file_enabled(self, enabled: Any) -> None:
        normalized = bool(enabled)
        if self.config.output.file.enabled == normalized:
            return

        self.config.output.file.enabled = normalized
        persist_error = self._persist_config("output file enabled")
        await self._broadcast_config()
        await self._broadcast(
            {
                "type": "toast",
                "message": f"File output {'on' if normalized else 'off'}",
                "level": "success",
            }
        )
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"File output applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_output_file_path(self, path: Any) -> None:
        raw = str(path or "").strip()
        if not raw:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": "Output file path cannot be empty",
                    "level": "error",
                }
            )
            await self._broadcast_config()
            return

        normalized = Path(raw).expanduser()
        if self.config.output.file.path == normalized:
            return

        self.config.output.file.path = normalized
        persist_error = self._persist_config("output file path")
        await self._broadcast_config()
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Output file path {normalized}",
                "level": "success",
            }
        )
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Output file path applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_model_path(self, path: Any) -> None:
        raw = "" if path is None else str(path).strip()
        next_path = str(Path(raw).expanduser()) if raw else None

        if self.config.model.path == next_path:
            return

        previous_path = self.config.model.path
        self.config.model.path = next_path
        persist_error = self._persist_config("model path")

        try:
            await self._reload_transcriber()
        except Exception as exc:
            logger.exception("Failed to apply model path")
            self.config.model.path = previous_path
            rollback_error = self._persist_config("model path rollback")
            await self._broadcast_config()
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Failed to apply model path: {exc}",
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
        await self._broadcast(
            {
                "type": "toast",
                "message": (
                    "Local model path cleared (default cache)"
                    if next_path is None
                    else f"Local model path {next_path}"
                ),
                "level": "success",
            }
        )
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Model path applied, but failed to save: {persist_error}",
                    "level": "error",
                }
            )

    async def _set_theme(self, theme_name: str) -> None:
        normalized = str(theme_name).strip().lower()
        if not normalized:
            await self._broadcast(
                {"type": "toast", "message": "Theme cannot be empty", "level": "error"}
            )
            return

        if self.config.ui.theme == normalized:
            return

        self.config.ui.theme = normalized
        persist_error = self._persist_config("theme")

        await self._broadcast_config()
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Theme {normalized}",
                "level": "success",
            }
        )
        if persist_error:
            await self._broadcast(
                {
                    "type": "toast",
                    "message": f"Theme applied, but failed to save: {persist_error}",
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
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Hotkey set to {hotkey}",
                "level": "success",
            }
        )
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
        await self._broadcast(
            {
                "type": "toast",
                "message": f"Hotkey mode {normalized}",
                "level": "success",
            }
        )

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
                "models": self._serialize_models(models),
            })
        )

    async def _broadcast_models(self) -> None:
        """Broadcast model list to all clients."""
        models = list_installed_models()
        await self._broadcast({
            "type": "models",
            "models": self._serialize_models(models),
        })

    def _serialize_models(self, models: list[Any]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for model in models:
            variants: dict[str, Any] = {}
            for runtime in RUNTIME_NAMES:
                variant = model.variants.get(runtime)
                if variant is None:
                    continue
                variants[runtime] = {
                    "runtime": variant.runtime,
                    "format": variant.format,
                    "installed": variant.installed,
                    "path": str(variant.path) if variant.path else None,
                    "size_bytes": variant.size_bytes,
                    "size_estimated": variant.size_estimated,
                }
            payload.append({"name": model.name, "variants": variants})
        return payload

    async def _set_welcome_shown(self) -> None:
        """Mark the welcome journey as shown and persist to config."""
        self.config.ui.welcome_shown = True
        try:
            save_config(self.config)
        except Exception:
            logger.exception("Failed to persist welcome_shown config")
        await self._broadcast_config()

    async def _send_capabilities(self, websocket: WebSocketServerProtocol) -> None:
        """Send runtime capabilities with a recommended runtime/device to a client."""
        import sys
        caps = self._runtime_capabilities or {}
        model_caps = caps.get("model", {})
        devices_by_runtime = model_caps.get("devices_by_runtime", {})

        # Build recommendation
        recommended_runtime = "faster-whisper"
        recommended_device = "cpu"

        # Check for MPS (Mac with Apple Silicon)
        wcpp_devices = devices_by_runtime.get("whisper.cpp", {})
        if sys.platform == "darwin" and wcpp_devices.get("mps", {}).get("enabled"):
            recommended_runtime = "whisper.cpp"
            recommended_device = "mps"
        else:
            # Check for CUDA
            fw_devices = devices_by_runtime.get("faster-whisper", {})
            if fw_devices.get("cuda", {}).get("enabled"):
                recommended_runtime = "faster-whisper"
                recommended_device = "cuda"

        await websocket.send(json.dumps({
            "type": "capabilities",
            "capabilities": caps,
            "recommended": {
                "runtime": recommended_runtime,
                "device": recommended_device,
            },
        }))

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
        """
        Build the configuration payload used to synchronize state with connected clients.

        Refreshes cached runtime capability information and returns a dictionary containing the serialized application config extended with bridge connection info and runtime/UI flags such as `auto_copy`, `auto_paste`, `first_run_setup_required`, and `runtime` capabilities.

        Returns:
            dict[str, Any]: Serialized configuration payload for clients.
        """
        config_dict = self.config.to_dict()
        config_dict["bridge"] = {"host": "localhost", "port": 7878}
        config_dict["auto_copy"] = self._auto_copy
        config_dict["auto_paste"] = self._auto_paste
        config_dict["auto_revert_clipboard"] = self._auto_revert_clipboard
        config_dict["first_run_setup_required"] = self._first_run_setup_required
        config_dict["runtime"] = self._runtime_capabilities
        return config_dict

    def shutdown(self) -> None:
        """
        Initiates server shutdown and releases runtime resources.

        Signals shutdown, cancels any in-progress model downloads, stops the audio recorder if active, stops the global hotkey listener if running, and closes the noise suppression component.
        """
        self._shutdown_requested.set()
        pending_download_keys = self._download_queue.pending_keys()
        self._download_queue.cancel_all()
        for key in pending_download_keys:
            task = self._model_tasks.get(key)
            if task is None or task.done():
                continue
            task.cancel()
        if self.recorder and self._recording:
            try:
                self.recorder.stop()
            except Exception:
                logger.debug("Error stopping recorder during shutdown", exc_info=True)
            finally:
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
    """
    Start and run the WebSocket bridge server and its event loop until shutdown.

    Creates a BridgeServer using the provided AppConfig (or the loaded default) and runs it listening on the given host and port. The function runs the server loop until interrupted (e.g., Ctrl+C) and ensures the server is shut down and cleaned up on exit.

    Parameters:
        config (AppConfig | None): Optional application configuration. If omitted, the configuration is loaded from the default location.
        host (str): Hostname or IP address to bind the server to.
        port (int): TCP port to listen on.
        capture_logs (bool): If true, install the WebSocket log forwarder so server logs are sent to connected clients.
    """
    app_config = config or load_config()
    server = BridgeServer(app_config)
    try:
        asyncio.run(server.start(host, port, capture_logs=capture_logs))
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
