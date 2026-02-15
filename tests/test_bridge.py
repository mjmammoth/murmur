from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
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
    config.audio = Mock()
    config.audio.sample_rate = 16000
    config.audio.noise_suppression = Mock()
    config.audio.noise_suppression.enabled = False
    config.vad = Mock()
    config.vad.enabled = False
    config.vad.aggressiveness = 2
    config.model = Mock()
    config.model.name = 'tiny'
    config.model.backend = 'faster-whisper'
    config.model.device = 'cpu'
    config.model.compute_type = 'int8'
    config.model.path = None
    config.model.auto_download = True
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
         patch('whisper_local.bridge.Transcriber'), \
         patch('whisper_local.bridge.HotkeyListener'):

        server._init_components()

        assert server.recorder is not None
        assert server.noise is not None
        assert server.vad is not None
        assert server.transcriber is not None
        assert server.hotkey is not None


def test_bridge_server_detect_runtime_capabilities(mock_config):
    """Test _detect_runtime_capabilities calls detect_runtime_capabilities."""
    server = BridgeServer(mock_config)

    with patch('whisper_local.bridge.detect_runtime_capabilities') as mock_detect:
        mock_detect.return_value = {'backend': 'test'}

        result = server._detect_runtime_capabilities()

        assert result == {'backend': 'test'}
        mock_detect.assert_called_once_with('faster-whisper')


def test_bridge_server_refresh_runtime_capabilities_no_force_within_ttl(mock_config):
    """Test _refresh_runtime_capabilities skips refresh within TTL."""
    server = BridgeServer(mock_config)
    server._runtime_capabilities = {'old': 'data'}
    server._runtime_capabilities_dirty = False

    with patch('whisper_local.bridge.detect_runtime_capabilities') as mock_detect:
        server._refresh_runtime_capabilities(force=False)

        # Should not call detect since within TTL
        mock_detect.assert_not_called()


def test_bridge_server_refresh_runtime_capabilities_force(mock_config):
    """Test _refresh_runtime_capabilities forces refresh when force=True."""
    server = BridgeServer(mock_config)

    with patch('whisper_local.bridge.detect_runtime_capabilities') as mock_detect:
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
        MAX_DROP_AUDIO_SECONDS,
        MAX_DROP_FILE_BYTES,
        MAX_DROP_FILES,
    )

    assert isinstance(MAX_DROP_FILES, int)
    assert isinstance(MAX_DROP_FILE_BYTES, int)
    assert isinstance(MAX_DROP_AUDIO_SECONDS, int)
    assert isinstance(AUTO_PASTE_INPUT_SUPPRESS_MS, int)
