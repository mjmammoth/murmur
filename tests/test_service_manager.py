from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_local.service_manager import ServiceManager
from whisper_local.service_state import ServiceState


def test_status_returns_stopped_when_state_missing(tmp_path: Path) -> None:
    manager = ServiceManager(state_path=tmp_path / "service.json")

    status = manager.status()

    assert status.running is False
    assert status.pid is None
    assert status.stale is False


def test_status_marks_and_cleans_stale_state(tmp_path: Path) -> None:
    state_path = tmp_path / "service.json"
    state = ServiceState.new(pid=99999, host="localhost", port=7878, status_indicator_pid=None)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(f"{json.dumps(state.to_dict())}\n", encoding="utf-8")
    manager = ServiceManager(state_path=state_path)

    with patch("whisper_local.service_manager._is_pid_alive", return_value=False):
        status = manager.status()

    assert status.running is False
    assert status.stale is True
    assert status.pid == 99999
    assert state_path.exists() is False


def test_start_background_persists_service_state(tmp_path: Path) -> None:
    state_path = tmp_path / "service.json"
    manager = ServiceManager(state_path=state_path, python_executable="/usr/bin/python3")

    process = Mock()
    process.pid = 1234
    indicator_provider = Mock()
    indicator_provider.pid = 5678

    with patch("whisper_local.service_manager.subprocess.Popen", return_value=process), patch(
        "whisper_local.service_manager._wait_for_port", return_value=True
    ), patch(
        "whisper_local.service_manager._is_pid_alive", return_value=True
    ), patch(
        "whisper_local.service_manager._is_port_reachable", return_value=True
    ), patch(
        "whisper_local.service_manager.create_status_indicator_provider",
        return_value=indicator_provider,
    ):
        status = manager.start_background(host="localhost", port=7878, status_indicator=True)

    assert status.running is True
    assert state_path.exists()
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["pid"] == 1234
    assert saved["host"] == "localhost"
    assert saved["port"] == 7878


def test_start_background_restarts_when_existing_state_target_differs(tmp_path: Path) -> None:
    state_path = tmp_path / "service.json"
    existing_state = ServiceState.new(
        pid=4444,
        host="localhost",
        port=7878,
        status_indicator_pid=5555,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(f"{json.dumps(existing_state.to_dict())}\n", encoding="utf-8")
    manager = ServiceManager(state_path=state_path, python_executable="/usr/bin/python3")
    process = Mock()
    process.pid = 7777

    replacement_status = Mock()
    replacement_status.running = True
    replacement_status.pid = 7777
    replacement_status.host = "127.0.0.1"
    replacement_status.port = 9000

    with patch("whisper_local.service_manager.subprocess.Popen", return_value=process), patch(
        "whisper_local.service_manager._wait_for_port", return_value=True
    ), patch(
        "whisper_local.service_manager._is_pid_alive", return_value=True
    ), patch(
        "whisper_local.service_manager._terminate_pid"
    ) as mock_terminate, patch.object(
        manager, "status", return_value=replacement_status
    ):
        status = manager.start_background(host="127.0.0.1", port=9000, status_indicator=False)

    mock_terminate.assert_any_call(4444)
    mock_terminate.assert_any_call(5555)
    assert status.running is True
    assert status.pid == 7777
    assert status.host == "127.0.0.1"
    assert status.port == 9000


def test_start_background_indicator_start_failure_cleans_bridge_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "service.json"
    manager = ServiceManager(state_path=state_path, python_executable="/usr/bin/python3")
    process = Mock()
    process.pid = 1234
    indicator_provider = Mock()
    indicator_provider.pid = 5678
    indicator_provider.start.side_effect = RuntimeError("indicator start failed")
    monkeypatch.setattr("whisper_local.service_manager.sys.platform", "darwin")

    with patch("whisper_local.service_manager.subprocess.Popen", return_value=process), patch(
        "whisper_local.service_manager._wait_for_port", return_value=True
    ), patch(
        "whisper_local.service_manager.create_status_indicator_provider",
        return_value=indicator_provider,
    ), patch("whisper_local.service_manager._terminate_pid") as mock_terminate:
        with pytest.raises(RuntimeError, match="indicator start failed"):
            manager.start_background(host="localhost", port=7878, status_indicator=True)

    indicator_provider.stop.assert_called_once()
    mock_terminate.assert_called_once_with(1234, timeout=1.0)
    assert state_path.exists() is False


def test_stop_is_idempotent_when_state_missing(tmp_path: Path) -> None:
    manager = ServiceManager(state_path=tmp_path / "service.json")

    status = manager.stop()

    assert status.running is False
    assert status.pid is None


def test_stop_terminates_service_and_indicator(tmp_path: Path) -> None:
    state_path = tmp_path / "service.json"
    manager = ServiceManager(state_path=state_path)
    state = ServiceState.new(pid=1234, host="localhost", port=7878, status_indicator_pid=5678)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(f"{json.dumps(state.to_dict())}\n", encoding="utf-8")

    with patch("whisper_local.service_manager._terminate_pid") as mock_terminate:
        manager.stop()

    assert mock_terminate.call_count == 2
    mock_terminate.assert_any_call(1234)
    mock_terminate.assert_any_call(5678, timeout=1.5)
    assert state_path.exists() is False


def test_ensure_running_starts_service_when_not_running(tmp_path: Path) -> None:
    manager = ServiceManager(state_path=tmp_path / "service.json")
    with patch.object(manager, "status") as mock_status, patch.object(
        manager, "start_background"
    ) as mock_start:
        mock_status.return_value = Mock(running=False)
        mock_start.return_value = Mock(running=True)

        status = manager.ensure_running(host="localhost", port=7878, status_indicator=True)

    mock_start.assert_called_once_with(host="localhost", port=7878, status_indicator=True)
    assert status.running is True
