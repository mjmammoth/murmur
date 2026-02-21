from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from time import monotonic
from unittest.mock import AsyncMock, Mock, patch

import pytest

from whisper_local.bridge import (
    BridgeLogFilter,
    BridgeServer,
    WebSocketLogHandler,
)
from whisper_local.config import AppConfig


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    config = Mock(spec=AppConfig)
    config.auto_copy = False
    config.auto_paste = False
    config.auto_revert_clipboard = True
    config.audio = Mock()
    config.audio.sample_rate = 16000
    config.audio.noise_suppression = Mock()
    config.audio.noise_suppression.enabled = False
    config.vad = Mock()
    config.vad.enabled = False
    config.vad.aggressiveness = 2
    config.model = Mock()
    config.model.name = 'tiny'
    config.model.runtime = 'faster-whisper'
    config.model.device = 'cpu'
    config.model.compute_type = 'int8'
    config.model.path = None
    config.model.language = None
    config.hotkey = Mock()
    config.hotkey.key = 'f3'
    config.hotkey.mode = 'ptt'
    config.ui = Mock()
    config.ui.theme = 'default'
    config.output = Mock()
    config.output.clipboard = False
    config.output.file = Mock()
    config.output.file.enabled = False
    config.output.file.path = Path('/tmp/output.txt')
    return config


def test_bridge_log_filter_blocks_websocket_handshake_errors():
    """Test BridgeLogFilter blocks websockets handshake errors."""
    log_filter = BridgeLogFilter()

    record = logging.LogRecord(
        name='websockets.server',
        level=logging.ERROR,
        pathname='',
        lineno=0,
        msg='opening handshake failed',
        args=(),
        exc_info=None
    )

    assert not log_filter.filter(record)


def test_bridge_log_filter_blocks_websocket_asyncio_handshake_errors():
    """Test BridgeLogFilter blocks websockets.asyncio handshake errors."""
    log_filter = BridgeLogFilter()

    record = logging.LogRecord(
        name='websockets.asyncio.server',
        level=logging.ERROR,
        pathname='',
        lineno=0,
        msg='connection opening handshake failed',
        args=(),
        exc_info=None
    )

    assert not log_filter.filter(record)


def test_bridge_log_filter_allows_whisper_local_info():
    """Test BridgeLogFilter allows whisper_local INFO logs."""
    log_filter = BridgeLogFilter()

    record = logging.LogRecord(
        name='whisper_local.bridge',
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg='Bridge server running',
        args=(),
        exc_info=None
    )

    assert log_filter.filter(record)


def test_bridge_log_filter_blocks_whisper_local_debug():
    """Test BridgeLogFilter blocks whisper_local DEBUG logs."""
    log_filter = BridgeLogFilter()

    record = logging.LogRecord(
        name='whisper_local.bridge',
        level=logging.DEBUG,
        pathname='',
        lineno=0,
        msg='Debug message',
        args=(),
        exc_info=None
    )

    assert not log_filter.filter(record)


def test_bridge_log_filter_allows_other_warnings():
    """Test BridgeLogFilter allows WARNING logs from other modules."""
    log_filter = BridgeLogFilter()

    record = logging.LogRecord(
        name='some.other.module',
        level=logging.WARNING,
        pathname='',
        lineno=0,
        msg='Warning message',
        args=(),
        exc_info=None
    )

    assert log_filter.filter(record)


def test_bridge_log_filter_allows_websocket_non_handshake_errors():
    """Test BridgeLogFilter allows websocket errors that are not handshake-related."""
    log_filter = BridgeLogFilter()

    record = logging.LogRecord(
        name='websockets.server',
        level=logging.ERROR,
        pathname='',
        lineno=0,
        msg='connection closed unexpectedly',
        args=(),
        exc_info=None
    )

    # Should be allowed since it's WARNING level for non-whisper_local
    assert log_filter.filter(record)


def test_bridge_server_init(mock_config):
    """Test BridgeServer initialization."""
    server = BridgeServer(mock_config)

    assert server.config == mock_config
    assert server.clients == set()
    assert server._recording is False
    assert server._auto_copy is False
    assert server._auto_paste is False
    assert server._model_loaded is False


def test_bridge_server_init_forces_auto_copy_when_auto_paste_enabled(mock_config):
    """Auto paste startup state should always imply auto copy."""
    mock_config.auto_copy = False
    mock_config.auto_paste = True

    with patch('whisper_local.bridge.save_config') as mock_save:
        with patch('whisper_local.bridge.logger') as mock_logger:
            server = BridgeServer(mock_config)

    assert server._auto_paste is True
    assert server._auto_copy is True
    assert mock_config.auto_copy is True
    mock_save.assert_called_once_with(mock_config)
    mock_logger.info.assert_called_once_with(
        'Auto paste enabled in config; forcing auto copy on'
    )


def test_toggle_auto_copy_is_blocked_while_auto_paste_enabled(mock_config):
    """Disabling auto copy should be rejected when auto paste is on."""
    server = BridgeServer(mock_config)
    server._auto_copy = True
    server._auto_paste = True
    mock_config.auto_copy = True
    mock_config.auto_paste = True
    server._broadcast = AsyncMock()
    server._broadcast_config = AsyncMock()

    with patch('whisper_local.bridge.save_config') as mock_save:
        with patch('whisper_local.bridge.logger') as mock_logger:
            asyncio.run(
                server._handle_message(
                    Mock(),
                    json.dumps({'type': 'toggle_auto_copy', 'enabled': False}),
                )
            )

    assert server._auto_copy is True
    assert mock_config.auto_copy is True
    mock_save.assert_not_called()
    server._broadcast.assert_awaited_once_with(
        {
            'type': 'toast',
            'message': 'Auto copy remains on while auto paste is enabled',
            'level': 'info',
        }
    )
    server._broadcast_config.assert_awaited_once()
    mock_logger.info.assert_called_once_with(
        'Rejected auto copy disable request because auto paste is enabled'
    )


def test_toggle_auto_paste_enables_auto_copy(mock_config):
    """Enabling auto paste should automatically enable auto copy."""
    server = BridgeServer(mock_config)
    server._auto_copy = False
    server._auto_paste = False
    mock_config.auto_copy = False
    mock_config.auto_paste = False
    server._broadcast = AsyncMock()
    server._broadcast_config = AsyncMock()

    with patch('whisper_local.bridge.save_config') as mock_save:
        with patch('whisper_local.bridge.logger') as mock_logger:
            asyncio.run(
                server._handle_message(
                    Mock(),
                    json.dumps({'type': 'toggle_auto_paste', 'enabled': True}),
                )
            )

    assert server._auto_paste is True
    assert server._auto_copy is True
    assert mock_config.auto_paste is True
    assert mock_config.auto_copy is True
    mock_save.assert_called_once_with(mock_config)
    server._broadcast.assert_awaited_once_with(
        {
            'type': 'toast',
            'message': 'Auto paste on; auto copy on',
            'level': 'success',
        }
    )
    server._broadcast_config.assert_awaited_once()
    mock_logger.info.assert_called_once_with('Auto paste enabled; forcing auto copy on')


def test_toggle_auto_revert_clipboard_persists_and_broadcasts(mock_config):
    """Toggling auto revert clipboard should persist and broadcast config."""
    server = BridgeServer(mock_config)
    server._auto_revert_clipboard = True
    mock_config.auto_revert_clipboard = True
    server._broadcast = AsyncMock()
    server._broadcast_config = AsyncMock()

    with patch('whisper_local.bridge.save_config') as mock_save:
        asyncio.run(
            server._handle_message(
                Mock(),
                json.dumps({'type': 'toggle_auto_revert_clipboard', 'enabled': False}),
            )
        )

    assert server._auto_revert_clipboard is False
    assert mock_config.auto_revert_clipboard is False
    mock_save.assert_called_once_with(mock_config)
    server._broadcast.assert_awaited_once_with(
        {
            'type': 'toast',
            'message': 'Auto revert clipboard off',
            'level': 'success',
        }
    )
    server._broadcast_config.assert_awaited_once()


def test_config_payload_includes_auto_revert_clipboard(mock_config):
    """Bridge config payload should include auto_revert_clipboard flag."""
    server = BridgeServer(mock_config)
    server._auto_revert_clipboard = False
    mock_config.to_dict.return_value = {"model": {"runtime": "faster-whisper"}}

    payload = server._config_payload()

    assert payload["auto_revert_clipboard"] is False


def test_process_audio_auto_paste_reverts_clipboard_in_order(mock_config):
    """Auto-paste with auto-revert should snapshot, paste, and restore in order."""
    server = BridgeServer(mock_config)
    server._auto_paste = True
    server._auto_copy = True
    server._auto_revert_clipboard = True
    server._broadcast = AsyncMock()

    mock_config.output.clipboard = False
    mock_config.output.file.enabled = False
    mock_config.vad.enabled = False

    audio = Mock()
    audio.size = 4
    audio.shape = (4,)

    result = Mock()
    result.text = "hello world"
    result.language = "en"

    transcriber = Mock()
    transcriber.transcribe.return_value = result
    transcriber.runtime_info.return_value = {}

    call_order: list[str] = []
    snapshot = object()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with patch("whisper_local.bridge.capture_clipboard_snapshot") as mock_capture, patch(
        "whisper_local.bridge.copy_to_clipboard"
    ) as mock_copy, patch("whisper_local.bridge.paste_from_clipboard") as mock_paste, patch(
        "whisper_local.bridge.restore_clipboard_snapshot"
    ) as mock_restore, patch(
        "whisper_local.bridge.asyncio.to_thread", side_effect=fake_to_thread
    ), patch("whisper_local.bridge.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_capture.side_effect = lambda: call_order.append("capture") or snapshot
        mock_copy.side_effect = lambda text: call_order.append("copy") or True
        mock_paste.side_effect = lambda: call_order.append("paste") or True
        mock_restore.side_effect = lambda snap: call_order.append("restore") or True

        asyncio.run(
            server._process_audio(
                audio,
                transcriber=transcriber,
                language=None,
                sample_rate=mock_config.audio.sample_rate,
            )
        )

    assert call_order == ["capture", "copy", "paste", "restore"]
    mock_sleep.assert_awaited_once_with(0.12)
    suppress_payloads = [
        call.args[0]
        for call in server._broadcast.await_args_list
        if call.args and call.args[0].get("type") == "suppress_paste_input"
    ]
    assert len(suppress_payloads) == 1


def test_process_audio_auto_paste_without_revert_does_not_restore(mock_config):
    """Auto-paste without auto-revert should not capture or restore clipboard."""
    server = BridgeServer(mock_config)
    server._auto_paste = True
    server._auto_copy = True
    server._auto_revert_clipboard = False
    server._broadcast = AsyncMock()

    mock_config.output.clipboard = False
    mock_config.output.file.enabled = False
    mock_config.vad.enabled = False

    audio = Mock()
    audio.size = 4
    audio.shape = (4,)

    result = Mock()
    result.text = "hello world"
    result.language = "en"

    transcriber = Mock()
    transcriber.transcribe.return_value = result
    transcriber.runtime_info.return_value = {}

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with patch("whisper_local.bridge.capture_clipboard_snapshot") as mock_capture, patch(
        "whisper_local.bridge.copy_to_clipboard", return_value=True
    ), patch("whisper_local.bridge.paste_from_clipboard", return_value=True), patch(
        "whisper_local.bridge.restore_clipboard_snapshot"
    ) as mock_restore, patch("whisper_local.bridge.asyncio.to_thread", side_effect=fake_to_thread):
        asyncio.run(
            server._process_audio(
                audio,
                transcriber=transcriber,
                language=None,
                sample_rate=mock_config.audio.sample_rate,
            )
        )

    mock_capture.assert_not_called()
    mock_restore.assert_not_called()


def test_process_audio_auto_paste_revert_attempted_when_paste_fails(mock_config):
    """Clipboard restore should still be attempted when paste command fails."""
    server = BridgeServer(mock_config)
    server._auto_paste = True
    server._auto_copy = True
    server._auto_revert_clipboard = True
    server._broadcast = AsyncMock()

    mock_config.output.clipboard = False
    mock_config.output.file.enabled = False
    mock_config.vad.enabled = False

    audio = Mock()
    audio.size = 4
    audio.shape = (4,)

    result = Mock()
    result.text = "hello world"
    result.language = "en"

    transcriber = Mock()
    transcriber.transcribe.return_value = result
    transcriber.runtime_info.return_value = {}

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with patch("whisper_local.bridge.capture_clipboard_snapshot", return_value=object()), patch(
        "whisper_local.bridge.copy_to_clipboard", return_value=True
    ), patch("whisper_local.bridge.paste_from_clipboard", return_value=False), patch(
        "whisper_local.bridge.restore_clipboard_snapshot", return_value=True
    ) as mock_restore, patch(
        "whisper_local.bridge.asyncio.to_thread", side_effect=fake_to_thread
    ), patch("whisper_local.bridge.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        asyncio.run(
            server._process_audio(
                audio,
                transcriber=transcriber,
                language=None,
                sample_rate=mock_config.audio.sample_rate,
            )
        )

    mock_restore.assert_called_once()
    mock_sleep.assert_not_awaited()


def test_bridge_server_spawn_task():
    """Test _spawn_task creates and tracks tasks."""
    config = Mock()
    server = BridgeServer(config)

    async def dummy_coro():
        return "result"

    with patch('asyncio.create_task') as mock_create_task:
        mock_task = Mock()
        mock_create_task.return_value = mock_task

        result = server._spawn_task(dummy_coro())

        assert result == mock_task
        assert mock_task in server._background_tasks
        mock_task.add_done_callback.assert_called_once()


def test_bridge_server_on_task_done_removes_task():
    """Test _on_task_done removes task from background tasks."""
    config = Mock()
    server = BridgeServer(config)

    mock_task = Mock()
    mock_task.cancelled.return_value = False
    mock_task.exception.return_value = None
    server._background_tasks.add(mock_task)

    server._on_task_done(mock_task)

    assert mock_task not in server._background_tasks


def test_bridge_server_on_task_done_logs_exception():
    """Test _on_task_done logs exception from failed task."""
    config = Mock()
    server = BridgeServer(config)

    mock_task = Mock()
    mock_task.cancelled.return_value = False
    mock_task.exception.return_value = RuntimeError("Task failed")
    server._background_tasks.add(mock_task)

    with patch('whisper_local.bridge.logger') as mock_logger:
        server._on_task_done(mock_task)

        mock_logger.error.assert_called_once()


def test_bridge_server_spawn_model_task_cancels_existing():
    """Test _spawn_model_task cancels existing task for same model."""
    config = Mock()
    server = BridgeServer(config)

    existing_task = Mock()
    existing_task.done.return_value = False
    server._model_tasks['tiny'] = existing_task

    async def dummy_coro():
        pass

    with patch('asyncio.create_task') as mock_create_task:
        mock_new_task = Mock()
        mock_create_task.return_value = mock_new_task

        server._spawn_model_task('tiny', dummy_coro())

        existing_task.cancel.assert_called_once()
        assert server._model_tasks['tiny'] == mock_new_task


def test_cancel_model_download_cancels_queued_task_without_error(mock_config):
    """Queued downloads should cancel cleanly instead of reporting no-active errors."""
    server = BridgeServer(mock_config)
    queued_task = Mock()
    queued_task.done.return_value = False
    server._download_queue.enqueue_download(
        "faster-whisper:small",
        model="small",
        runtime="faster-whisper",
        task=queued_task,
    )
    server._broadcast = AsyncMock()

    asyncio.run(server._cancel_model_download("small", runtime="faster-whisper"))

    queued_task.cancel.assert_called_once()
    server._broadcast.assert_awaited_once_with(
        {
            "type": "toast",
            "message": "Cancelled queued download small.",
            "model": "small",
            "runtime": "faster-whisper",
            "action": "download_cancelled",
            "level": "info",
        }
    )


def test_cancel_model_download_infers_single_queued_task(mock_config):
    """Blank cancel requests should resolve a single queued download."""
    server = BridgeServer(mock_config)
    queued_task = Mock()
    queued_task.done.return_value = False
    server._download_queue.enqueue_download(
        "whisper.cpp:base",
        model="base",
        runtime="whisper.cpp",
        task=queued_task,
    )
    server._broadcast = AsyncMock()

    asyncio.run(server._cancel_model_download("", runtime=None))

    queued_task.cancel.assert_called_once()
    server._broadcast.assert_awaited_once_with(
        {
            "type": "toast",
            "message": "Cancelled queued download base.",
            "model": "base",
            "runtime": "whisper.cpp",
            "action": "download_cancelled",
            "level": "info",
        }
    )


def test_cancel_model_download_is_idempotent_without_error_toast(mock_config):
    server = BridgeServer(mock_config)
    queued_task = Mock()
    queued_task.done.return_value = False
    server._download_queue.enqueue_download(
        "faster-whisper:small",
        model="small",
        runtime="faster-whisper",
        task=queued_task,
    )
    server._broadcast = AsyncMock()

    asyncio.run(server._cancel_model_download("small", runtime="faster-whisper"))
    asyncio.run(server._cancel_model_download("small", runtime="faster-whisper"))

    messages = [call.args[0]["message"] for call in server._broadcast.await_args_list if call.args]
    assert "No active download matches request" not in messages


def test_cancel_all_model_downloads_cancels_queued_entries(mock_config):
    server = BridgeServer(mock_config)
    first_task = Mock()
    first_task.done.return_value = False
    second_task = Mock()
    second_task.done.return_value = False
    server._download_queue.enqueue_download(
        "faster-whisper:small",
        model="small",
        runtime="faster-whisper",
        task=first_task,
    )
    server._download_queue.enqueue_download(
        "whisper.cpp:base",
        model="base",
        runtime="whisper.cpp",
        task=second_task,
    )
    server._broadcast = AsyncMock()

    asyncio.run(server._cancel_all_model_downloads())

    first_task.cancel.assert_called_once()
    second_task.cancel.assert_called_once()


def test_bridge_server_client_path_legacy_api():
    """Test _client_path returns path from legacy websockets API."""
    config = Mock()
    server = BridgeServer(config)

    mock_websocket = Mock()
    mock_websocket.path = '/ws?client=status-indicator'

    path = server._client_path(mock_websocket)
    assert path == '/ws?client=status-indicator'


def test_bridge_server_client_path_new_api():
    """Test _client_path returns path from new websockets API."""
    config = Mock()
    server = BridgeServer(config)

    mock_websocket = Mock()
    del mock_websocket.path  # Simulate new API without .path
    mock_websocket.request = Mock()
    mock_websocket.request.path = '/ws?client=passive'

    path = server._client_path(mock_websocket)
    assert path == '/ws?client=passive'


def test_bridge_server_client_path_fallback():
    """Test _client_path returns empty string when no path available."""
    config = Mock()
    server = BridgeServer(config)

    mock_websocket = Mock()
    del mock_websocket.path
    mock_websocket.request = None

    path = server._client_path(mock_websocket)
    assert path == ''


def test_bridge_server_is_passive_client_status_indicator():
    """Test _is_passive_client identifies status-indicator clients."""
    config = Mock()
    server = BridgeServer(config)

    mock_websocket = Mock()
    mock_websocket.path = '/ws?client=status-indicator'

    assert server._is_passive_client(mock_websocket) is True


def test_bridge_server_is_passive_client_passive():
    """Test _is_passive_client identifies passive clients."""
    config = Mock()
    server = BridgeServer(config)

    mock_websocket = Mock()
    mock_websocket.path = '/ws?client=passive'

    assert server._is_passive_client(mock_websocket) is True


def test_bridge_server_is_passive_client_normal():
    """Test _is_passive_client returns False for normal clients."""
    config = Mock()
    server = BridgeServer(config)

    mock_websocket = Mock()
    mock_websocket.path = '/ws'

    assert server._is_passive_client(mock_websocket) is False


def test_bridge_server_has_active_clients():
    """Test _has_active_clients correctly identifies active clients."""
    config = Mock()
    server = BridgeServer(config)

    active_client = Mock()
    passive_client = Mock()

    server.clients = {active_client, passive_client}
    server._passive_clients = {passive_client}

    assert server._has_active_clients() is True


def test_bridge_server_has_no_active_clients():
    """Test _has_active_clients returns False when only passive clients."""
    config = Mock()
    server = BridgeServer(config)

    passive_client = Mock()

    server.clients = {passive_client}
    server._passive_clients = {passive_client}

    assert server._has_active_clients() is False


def test_bridge_server_active_client_count():
    """Test _active_client_count returns correct count."""
    config = Mock()
    server = BridgeServer(config)

    active1 = Mock()
    active2 = Mock()
    passive = Mock()

    server.clients = {active1, active2, passive}
    server._passive_clients = {passive}

    assert server._active_client_count() == 2


def test_bridge_server_installed_model_names():
    """Test _installed_model_names returns installed model names."""
    config = Mock()
    server = BridgeServer(config)

    with patch('whisper_local.bridge.list_installed_models') as mock_list:
        mock_model1 = Mock(installed=True)
        mock_model1.name = 'tiny'
        mock_model2 = Mock(installed=False)
        mock_model2.name = 'base'
        mock_model3 = Mock(installed=True)
        mock_model3.name = 'small'
        mock_list.return_value = [mock_model1, mock_model2, mock_model3]

        result = server._installed_model_names()

        assert result == ['tiny', 'small']


def test_bridge_server_installed_model_names_backend_aware():
    """Test _installed_model_names filters by runtime variant install state."""
    config = Mock()
    config.model = Mock()
    config.model.runtime = "faster-whisper"
    server = BridgeServer(config)

    with patch("whisper_local.bridge.list_installed_models") as mock_list:
        tiny = Mock()
        tiny.name = "tiny"
        tiny.variants = {
            "faster-whisper": Mock(installed=True),
            "whisper.cpp": Mock(installed=False),
        }
        base = Mock()
        base.name = "base"
        base.variants = {
            "faster-whisper": Mock(installed=False),
            "whisper.cpp": Mock(installed=True),
        }
        mock_list.return_value = [tiny, base]

        assert server._installed_model_names("faster-whisper") == ["tiny"]
        assert server._installed_model_names("whisper.cpp") == ["base"]


def test_bridge_server_set_model_runtime_missing_variant_emits_requirement_event(mock_config):
    """Switching runtime without required variant should emit requirement event and keep runtime."""
    server = BridgeServer(mock_config)
    server._first_run_setup_required = False
    server._broadcast = AsyncMock()
    server._broadcast_config = AsyncMock()

    capabilities = {
        "model": {
            "runtimes": {
                "whisper.cpp": {"enabled": True, "reason": None},
            },
            "devices": {},
            "compute_types_by_device": {},
        }
    }

    with patch.object(server, "_detect_runtime_capabilities", return_value=capabilities), patch(
        "whisper_local.bridge.get_installed_model_path",
        return_value=None,
    ):
        asyncio.run(server._set_model_runtime("whisper.cpp"))

    assert mock_config.model.runtime == "faster-whisper"

    payloads = [call.args[0] for call in server._broadcast.await_args_list if call.args]
    requirement_payload = next(
        (payload for payload in payloads if payload.get("type") == "runtime_switch_requires_model_variant"),
        None,
    )
    assert requirement_payload is not None
    assert requirement_payload["runtime"] == "whisper.cpp"
    assert requirement_payload["model"] == "tiny"
    assert requirement_payload["format"] == "ggml"


def test_bridge_server_set_model_runtime_first_run_missing_variant_applies_without_prompt(mock_config):
    """First-run runtime switch should apply config without model-variant requirement prompt."""
    server = BridgeServer(mock_config)
    server._first_run_setup_required = True
    server._broadcast = AsyncMock()
    server._broadcast_config = AsyncMock()
    server._reload_transcriber = AsyncMock()

    capabilities = {
        "model": {
            "runtimes": {
                "whisper.cpp": {"enabled": True, "reason": None},
            },
            "devices": {
                "cpu": {"enabled": True, "reason": None},
                "mps": {"enabled": True, "reason": None},
                "cuda": {"enabled": False, "reason": "No CUDA GPU detected"},
            },
            "compute_types_by_device": {
                "cpu": ["default"],
                "mps": ["default"],
                "cuda": [],
            },
        }
    }

    with patch.object(server, "_detect_runtime_capabilities", return_value=capabilities), patch(
        "whisper_local.bridge.get_installed_model_path",
        return_value=None,
    ), patch.object(server, "_persist_config", return_value=None):
        asyncio.run(server._set_model_runtime("whisper.cpp"))

    assert mock_config.model.runtime == "whisper.cpp"
    assert mock_config.model.compute_type == "default"
    server._reload_transcriber.assert_not_awaited()

    payloads = [call.args[0] for call in server._broadcast.await_args_list if call.args]
    assert not any(
        payload.get("type") == "runtime_switch_requires_model_variant"
        for payload in payloads
    )
    assert any(
        payload.get("message") == "Model runtime whisper.cpp"
        for payload in payloads
    )


def test_bridge_server_set_model_device_first_run_persists_without_reload(mock_config):
    """First-run model device change should persist without transcriber reload."""
    server = BridgeServer(mock_config)
    server._first_run_setup_required = True
    server._broadcast = AsyncMock()
    server._broadcast_config = AsyncMock()
    server._reload_transcriber = AsyncMock()
    server._runtime_capabilities = {
        "model": {
            "devices": {
                "cpu": {"enabled": True, "reason": None},
                "mps": {"enabled": True, "reason": None},
                "cuda": {"enabled": False, "reason": "No CUDA GPU detected"},
            }
        }
    }

    with patch.object(server, "_persist_config", return_value=None), patch.object(
        server, "_refresh_runtime_capabilities"
    ):
        asyncio.run(server._set_model_device("mps"))

    assert mock_config.model.device == "mps"
    server._reload_transcriber.assert_not_awaited()
    payloads = [call.args[0] for call in server._broadcast.await_args_list if call.args]
    assert any(
        payload.get("message") == "Model device mps"
        for payload in payloads
    )


def test_bridge_server_download_progress_payload_includes_backend(mock_config):
    """Download progress payload should include runtime for variant-aware UI updates."""
    server = BridgeServer(mock_config)
    server._broadcast = AsyncMock()
    server._broadcast_models = AsyncMock()
    server._set_selected_model = AsyncMock()

    def fake_download_model(name, runtime, progress_callback=None, cancel_check=None):
        assert name == "tiny"
        assert runtime == "whisper.cpp"
        if progress_callback:
            progress_callback(35)

    with patch("whisper_local.bridge.download_model", side_effect=fake_download_model):
        asyncio.run(server._download_model("tiny", runtime="whisper.cpp"))

    payloads = [call.args[0] for call in server._broadcast.await_args_list if call.args]
    progress_payloads = [payload for payload in payloads if payload.get("type") == "download_progress"]
    assert any(
        payload.get("runtime") == "whisper.cpp" and payload.get("model") == "tiny"
        for payload in progress_payloads
    )
    assert any(
        payload.get("runtime") == "whisper.cpp" and payload.get("percent") == 100
        for payload in progress_payloads
    )


def test_bridge_server_has_installed_models_true():
    """Test _has_installed_models returns True when models installed."""
    config = Mock()
    server = BridgeServer(config)

    with patch('whisper_local.bridge.list_installed_models') as mock_list:
        mock_model = Mock(installed=True)
        mock_model.name = 'tiny'
        mock_list.return_value = [mock_model]

        assert server._has_installed_models() is True


def test_bridge_server_has_installed_models_false():
    """Test _has_installed_models returns False when no models installed."""
    config = Mock()
    server = BridgeServer(config)

    with patch('whisper_local.bridge.list_installed_models') as mock_list:
        mock_model = Mock(installed=False)
        mock_model.name = 'tiny'
        mock_list.return_value = [mock_model]

        assert server._has_installed_models() is False


def test_bridge_server_init_components(mock_config):
    """Test _init_components initializes all components."""
    server = BridgeServer(mock_config)

    with patch('whisper_local.bridge.AudioRecorder'), \
         patch('whisper_local.bridge.RNNoiseSuppressor'), \
         patch('whisper_local.bridge.VadProcessor'), \
         patch('whisper_local.bridge.HotkeyListener'):

        server._init_components()

        assert server.recorder is not None
        assert server.noise is not None
        assert server.vad is not None
        assert server.transcriber is None
        assert server.hotkey is not None


def test_bridge_server_detect_runtime_capabilities(mock_config):
    """Test _detect_runtime_capabilities calls detect_runtime_capabilities."""
    server = BridgeServer(mock_config)

    with patch('whisper_local.transcribe.detect_runtime_capabilities') as mock_detect:
        mock_detect.return_value = {'runtime': 'test'}

        result = server._detect_runtime_capabilities()

        assert result == {'runtime': 'test'}
        mock_detect.assert_called_once_with('faster-whisper')


def test_bridge_server_refresh_runtime_capabilities_no_force_within_ttl(mock_config):
    """Test _refresh_runtime_capabilities skips refresh within TTL."""
    server = BridgeServer(mock_config)
    server._runtime_capabilities = {'old': 'data'}
    server._runtime_capabilities_updated_at = monotonic()
    server._runtime_capabilities_dirty = False

    with patch('whisper_local.transcribe.detect_runtime_capabilities') as mock_detect:
        server._refresh_runtime_capabilities(force=False)

        # Should not call detect since within TTL
        mock_detect.assert_not_called()


def test_bridge_server_refresh_runtime_capabilities_force(mock_config):
    """Test _refresh_runtime_capabilities forces refresh when force=True."""
    server = BridgeServer(mock_config)

    with patch('whisper_local.transcribe.detect_runtime_capabilities') as mock_detect:
        mock_detect.return_value = {'new': 'data'}

        server._refresh_runtime_capabilities(force=True)

        mock_detect.assert_called_once()
        assert server._runtime_capabilities == {'new': 'data'}


def test_bridge_server_invalidate_runtime_capabilities(mock_config):
    """Test _invalidate_runtime_capabilities sets dirty flag."""
    server = BridgeServer(mock_config)
    server._runtime_capabilities_dirty = False

    server._invalidate_runtime_capabilities()

    assert server._runtime_capabilities_dirty is True


def test_bridge_server_set_runtime_capabilities(mock_config):
    """Test _set_runtime_capabilities updates capabilities and clears dirty flag."""
    server = BridgeServer(mock_config)
    server._runtime_capabilities_dirty = True

    new_caps = {'test': 'capabilities'}
    server._set_runtime_capabilities(new_caps)

    assert server._runtime_capabilities == new_caps
    assert server._runtime_capabilities_dirty is False


def test_bridge_server_persist_config_success(mock_config):
    """Test _persist_config saves config successfully."""
    server = BridgeServer(mock_config)

    with patch('whisper_local.bridge.save_config') as mock_save:
        result = server._persist_config('test context')

        assert result is None
        mock_save.assert_called_once_with(mock_config)


def test_bridge_server_persist_config_failure(mock_config):
    """Test _persist_config returns error message on failure."""
    server = BridgeServer(mock_config)

    with patch('whisper_local.bridge.save_config') as mock_save:
        mock_save.side_effect = Exception('Save failed')

        result = server._persist_config('test context')

        assert result == 'Save failed'


def test_bridge_server_extract_paths_from_paste_single_path():
    """Test _extract_paths_from_paste handles single file path."""
    config = Mock()
    server = BridgeServer(config)

    text = '/path/to/file.mp3'
    paths = server._extract_paths_from_paste(text)

    assert len(paths) >= 1


def test_bridge_server_extract_paths_from_paste_multiple_paths():
    """Test _extract_paths_from_paste handles multiple file paths."""
    config = Mock()
    server = BridgeServer(config)

    text = '/path/to/file1.mp3\n/path/to/file2.wav'
    paths = server._extract_paths_from_paste(text)

    assert len(paths) >= 2


def test_bridge_server_extract_paths_from_paste_quoted():
    """Test _extract_paths_from_paste handles quoted paths."""
    config = Mock()
    server = BridgeServer(config)

    text = '"/path/with spaces/file.mp3"'
    paths = server._extract_paths_from_paste(text)

    assert len(paths) >= 1


def test_bridge_server_normalize_paste_path_file_uri():
    """Test _normalize_paste_path handles file:// URIs."""
    config = Mock()
    server = BridgeServer(config)

    result = server._normalize_paste_path('file:///tmp/test.mp3')

    assert result is not None
    assert str(result).endswith('test.mp3')


def test_bridge_server_normalize_paste_path_empty():
    """Test _normalize_paste_path returns None for empty string."""
    config = Mock()
    server = BridgeServer(config)

    result = server._normalize_paste_path('')

    assert result is None


def test_bridge_server_normalize_paste_path_with_quotes():
    """Test _normalize_paste_path strips quotes."""
    config = Mock()
    server = BridgeServer(config)

    result = server._normalize_paste_path('"/tmp/test.mp3"')

    assert result is not None
    assert '"' not in str(result)


def test_bridge_server_shutdown_stops_recorder(mock_config):
    """Test shutdown stops recorder if recording."""
    server = BridgeServer(mock_config)
    server.recorder = Mock()
    server._recording = True

    server.shutdown()

    server.recorder.stop.assert_called_once()
    assert server._recording is False


def test_bridge_server_shutdown_stops_hotkey(mock_config):
    """Test shutdown stops hotkey if started."""
    server = BridgeServer(mock_config)
    server.hotkey = Mock()
    server._hotkey_started = True

    server.shutdown()

    server.hotkey.stop.assert_called_once()


def test_bridge_server_shutdown_closes_noise(mock_config):
    """Test shutdown closes noise suppressor."""
    server = BridgeServer(mock_config)
    server.noise = Mock()

    server.shutdown()

    server.noise.close.assert_called_once()


def test_bridge_server_shutdown_cancels_pending_download_tasks(mock_config):
    server = BridgeServer(mock_config)
    queued_task = Mock()
    queued_task.done.return_value = False
    server._download_queue.enqueue_download(
        "faster-whisper:tiny",
        model="tiny",
        runtime="faster-whisper",
        task=queued_task,
    )
    server._model_tasks["faster-whisper:tiny"] = queued_task

    server.shutdown()

    queued_task.cancel.assert_called()


def test_websocket_log_handler_emits_log_to_clients():
    """Test WebSocketLogHandler emits logs to bridge clients."""
    mock_bridge = Mock()
    mock_bridge.clients = [Mock()]
    mock_bridge._loop = Mock()
    mock_bridge._loop.is_closed.return_value = False

    handler = WebSocketLogHandler(mock_bridge)

    record = logging.LogRecord(
        name='test',
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg='Test message',
        args=(),
        exc_info=None
    )

    handler.emit(record)

    # Should attempt to broadcast
    assert mock_bridge._loop.is_closed.called


def test_websocket_log_handler_no_emit_without_clients():
    """Test WebSocketLogHandler doesn't emit when no clients connected."""
    mock_bridge = Mock()
    mock_bridge.clients = []

    handler = WebSocketLogHandler(mock_bridge)

    record = logging.LogRecord(
        name='test',
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg='Test message',
        args=(),
        exc_info=None
    )

    # Should not raise, just return early
    handler.emit(record)


def test_websocket_log_handler_handles_emit_errors():
    """Test WebSocketLogHandler handles errors during emit gracefully."""
    mock_bridge = Mock()
    mock_bridge.clients = [Mock()]
    mock_bridge._loop = Mock()
    mock_bridge._loop.is_closed.side_effect = Exception('Loop error')

    handler = WebSocketLogHandler(mock_bridge)

    record = logging.LogRecord(
        name='test',
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg='Test message',
        args=(),
        exc_info=None
    )

    # Should not raise, errors are caught
    handler.emit(record)


def test_constants_defined():
    """Test that bridge constants are defined."""
    from whisper_local.bridge import (
        AUTO_PASTE_INPUT_SUPPRESS_MS,
        AUTO_REVERT_CLIPBOARD_DELAY_MS,
        MAX_DROP_AUDIO_SECONDS,
        MAX_DROP_FILE_BYTES,
        MAX_DROP_FILES,
    )

    assert isinstance(MAX_DROP_FILES, int)
    assert isinstance(MAX_DROP_FILE_BYTES, int)
    assert isinstance(MAX_DROP_AUDIO_SECONDS, int)
    assert isinstance(AUTO_PASTE_INPUT_SUPPRESS_MS, int)
    assert isinstance(AUTO_REVERT_CLIPBOARD_DELAY_MS, int)
