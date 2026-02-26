from __future__ import annotations

import errno
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_local import service_manager
from whisper_local.service_manager import ServiceManager
from whisper_local.service_state import ServiceState


def test_is_pid_alive_treats_eperm_as_alive() -> None:
    with patch(
        "whisper_local.service_manager.os.kill",
        side_effect=OSError(errno.EPERM, "operation not permitted"),
    ):
        assert service_manager._is_pid_alive(1234) is True


def test_terminate_pid_attempts_non_blocking_waitpid_after_final_kill() -> None:
    expected_kill_signal = getattr(service_manager.signal, "SIGKILL", service_manager.signal.SIGTERM)
    expected_wnohang = getattr(service_manager.os, "WNOHANG", 0)

    with patch("whisper_local.service_manager._is_pid_alive", return_value=True), patch(
        "whisper_local.service_manager.os.kill"
    ) as mock_kill, patch(
        "whisper_local.service_manager.os.waitpid",
        create=True,
    ) as mock_waitpid:
        service_manager._terminate_pid(1234, timeout=0.0)

    mock_kill.assert_any_call(1234, service_manager.signal.SIGTERM)
    mock_kill.assert_any_call(1234, expected_kill_signal)
    mock_waitpid.assert_called_once_with(1234, expected_wnohang)


def test_terminate_pid_ignores_waitpid_errors() -> None:
    with patch("whisper_local.service_manager._is_pid_alive", return_value=True), patch(
        "whisper_local.service_manager.os.kill"
    ), patch(
        "whisper_local.service_manager.os.waitpid",
        side_effect=ChildProcessError,
        create=True,
    ):
        service_manager._terminate_pid(1234, timeout=0.0)


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


def test_status_marks_alive_but_unreachable_state_stale(tmp_path: Path) -> None:
    state_path = tmp_path / "service.json"
    state = ServiceState.new(
        pid=2222,
        host="localhost",
        port=7878,
        status_indicator_pid=3333,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(f"{json.dumps(state.to_dict())}\n", encoding="utf-8")
    manager = ServiceManager(state_path=state_path)

    with patch("whisper_local.service_manager._is_pid_alive", return_value=True), patch(
        "whisper_local.service_manager._is_port_reachable",
        return_value=False,
    ), patch("whisper_local.service_manager._terminate_pid") as mock_terminate:
        status = manager.status()

    assert status.running is False
    assert status.stale is True
    assert status.reachable is False
    assert status.pid == 2222
    assert status.host == "localhost"
    assert status.port == 7878
    assert status.status_indicator_pid == 3333
    mock_terminate.assert_any_call(2222)
    mock_terminate.assert_any_call(3333, timeout=1.5)
    assert state_path.exists() is False


def test_save_state_does_not_ensure_global_state_directory(tmp_path: Path) -> None:
    state_path = tmp_path / "custom-state" / "service.json"
    manager = ServiceManager(state_path=state_path)
    state = ServiceState.new(pid=1234, host="localhost", port=7878, status_indicator_pid=None)

    with patch("whisper_local.service_manager.ensure_state_directory") as mock_ensure_state_dir:
        manager.save_state(state)

    mock_ensure_state_dir.assert_not_called()
    assert state_path.exists()


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


def test_start_background_uses_indicator_provider_when_requested_on_non_darwin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "service.json"
    manager = ServiceManager(state_path=state_path, python_executable="/usr/bin/python3")

    process = Mock()
    process.pid = 1234
    indicator_provider = Mock()
    indicator_provider.pid = 5678
    monkeypatch.setattr("whisper_local.service_manager.sys.platform", "linux")

    with patch("whisper_local.service_manager.subprocess.Popen", return_value=process), patch(
        "whisper_local.service_manager._wait_for_port", return_value=True
    ), patch(
        "whisper_local.service_manager._is_pid_alive", return_value=True
    ), patch(
        "whisper_local.service_manager._is_port_reachable", return_value=True
    ), patch(
        "whisper_local.service_manager.create_status_indicator_provider",
        return_value=indicator_provider,
    ) as mock_create_indicator_provider:
        status = manager.start_background(host="localhost", port=7878, status_indicator=True)

    mock_create_indicator_provider.assert_called_once_with(
        host="localhost",
        port=7878,
        python_executable="/usr/bin/python3",
    )
    indicator_provider.start.assert_called_once()
    assert status.status_indicator_pid == 5678


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


def test_start_background_recovers_missing_indicator_on_darwin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    indicator_provider = Mock()
    indicator_provider.pid = 8888

    def _pid_alive(pid: int | None) -> bool:
        if pid == 4444:
            return True
        if pid == 5555:
            return False
        if pid == 7777:
            return True
        return False

    monkeypatch.setattr("whisper_local.service_manager.sys.platform", "darwin")
    with patch("whisper_local.service_manager.ensure_state_directory"), patch(
        "whisper_local.service_manager.subprocess.Popen",
        return_value=process,
    ), patch(
        "whisper_local.service_manager._wait_for_port",
        return_value=True,
    ), patch(
        "whisper_local.service_manager._is_pid_alive",
        side_effect=_pid_alive,
    ), patch(
        "whisper_local.service_manager._is_port_reachable",
        return_value=True,
    ), patch(
        "whisper_local.service_manager.create_status_indicator_provider",
        return_value=indicator_provider,
    ) as mock_create_indicator_provider, patch(
        "whisper_local.service_manager._terminate_pid"
    ) as mock_terminate:
        status = manager.start_background(host="localhost", port=7878, status_indicator=True)

    mock_terminate.assert_any_call(4444)
    mock_terminate.assert_any_call(5555)
    mock_create_indicator_provider.assert_called_once_with(
        host="localhost",
        port=7878,
        python_executable="/usr/bin/python3",
    )
    indicator_provider.start.assert_called_once()
    assert status.running is True
    assert status.pid == 7777
    assert status.host == "localhost"
    assert status.port == 7878
    assert status.status_indicator_pid == 8888


def test_start_background_non_darwin_does_not_restart_for_missing_indicator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "service.json"
    existing_state = ServiceState.new(
        pid=4444,
        host="localhost",
        port=7878,
        status_indicator_pid=None,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(f"{json.dumps(existing_state.to_dict())}\n", encoding="utf-8")
    manager = ServiceManager(state_path=state_path)
    existing_status = Mock(running=True, host="localhost", port=7878, pid=4444, status_indicator_pid=None)
    monkeypatch.setattr("whisper_local.service_manager.sys.platform", "linux")

    with patch(
        "whisper_local.service_manager._is_pid_alive",
        return_value=True,
    ), patch(
        "whisper_local.service_manager._is_port_reachable",
        return_value=True,
    ), patch.object(
        manager,
        "status",
        return_value=existing_status,
    ) as mock_status, patch(
        "whisper_local.service_manager.subprocess.Popen",
    ) as mock_popen, patch(
        "whisper_local.service_manager._terminate_pid"
    ) as mock_terminate:
        status = manager.start_background(host="localhost", port=7878, status_indicator=True)

    mock_status.assert_called_once()
    mock_popen.assert_not_called()
    mock_terminate.assert_not_called()
    assert status is existing_status


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


def test_ensure_running_returns_current_when_target_matches(tmp_path: Path) -> None:
    manager = ServiceManager(state_path=tmp_path / "service.json")
    current = Mock(running=True, host="localhost", port=7878)

    with patch.object(manager, "status", return_value=current), patch.object(
        manager,
        "start_background",
    ) as mock_start:
        status = manager.ensure_running(host="localhost", port=7878, status_indicator=False)

    mock_start.assert_not_called()
    assert status is current


def test_ensure_running_matching_target_with_status_indicator_uses_start_background(tmp_path: Path) -> None:
    manager = ServiceManager(state_path=tmp_path / "service.json")
    current = Mock(running=True, host="localhost", port=7878)
    replacement = Mock(running=True, host="localhost", port=7878)

    with patch.object(manager, "status", return_value=current), patch.object(
        manager,
        "start_background",
        return_value=replacement,
    ) as mock_start:
        status = manager.ensure_running(host="localhost", port=7878, status_indicator=True)

    mock_start.assert_called_once_with(host="localhost", port=7878, status_indicator=True)
    assert status is replacement


def test_ensure_running_restarts_when_running_target_differs(tmp_path: Path) -> None:
    manager = ServiceManager(state_path=tmp_path / "service.json")
    current = Mock(running=True, host="localhost", port=7878)
    replacement = Mock(running=True, host="127.0.0.1", port=9000)

    with patch.object(manager, "status", return_value=current), patch.object(
        manager,
        "start_background",
        return_value=replacement,
    ) as mock_start:
        status = manager.ensure_running(host="127.0.0.1", port=9000, status_indicator=False)

    mock_start.assert_called_once_with(host="127.0.0.1", port=9000, status_indicator=False)
    assert status is replacement
