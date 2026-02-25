from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from whisper_local.platform import create_status_indicator_provider
from whisper_local.service_state import (
    ServiceState,
    ServiceStatus,
    ensure_state_directory,
    service_state_path,
)


SERVICE_READY_TIMEOUT_SECONDS = 8.0
SERVICE_READY_POLL_SECONDS = 0.1

logger = logging.getLogger(__name__)


def _is_pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _is_port_reachable(host: str, port: int, *, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_port(host: str, port: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_port_reachable(host, port):
            return True
        time.sleep(SERVICE_READY_POLL_SECONDS)
    return _is_port_reachable(host, port)


def _terminate_pid(pid: int | None, *, timeout: float = 4.0) -> None:
    if not _is_pid_alive(pid):
        return
    assert pid is not None

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_pid_alive(pid):
            return
        time.sleep(0.1)

    kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    try:
        os.kill(pid, kill_signal)
    except OSError:
        return


class ServiceManager:
    def __init__(
        self,
        *,
        state_path: Path | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.state_path = (state_path or service_state_path()).expanduser()
        self.log_path = self.state_path.with_name("service.log")
        self.python_executable = python_executable or sys.executable

    def load_state(self) -> ServiceState | None:
        if not self.state_path.exists():
            return None
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return ServiceState.from_dict(payload)
        except Exception:
            return None

    def save_state(self, state: ServiceState) -> None:
        ensure_state_directory()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            f"{json.dumps(state.to_dict(), indent=2)}\n",
            encoding="utf-8",
        )

    def clear_state(self) -> None:
        if self.state_path.exists():
            self.state_path.unlink()

    def status(self) -> ServiceStatus:
        state = self.load_state()
        if state is None:
            return ServiceStatus(
                running=False,
                pid=None,
                host=None,
                port=None,
                started_at=None,
                status_indicator_pid=None,
                stale=False,
                reachable=False,
                state_path=self.state_path,
            )

        pid_alive = _is_pid_alive(state.pid)
        reachable = pid_alive and _is_port_reachable(state.host, state.port)
        stale = not pid_alive
        running = pid_alive and reachable
        if stale:
            self.clear_state()
            return ServiceStatus(
                running=False,
                pid=state.pid,
                host=state.host,
                port=state.port,
                started_at=state.started_at,
                status_indicator_pid=state.status_indicator_pid,
                stale=True,
                reachable=False,
                state_path=self.state_path,
            )

        return ServiceStatus(
            running=running,
            pid=state.pid,
            host=state.host,
            port=state.port,
            started_at=state.started_at,
            status_indicator_pid=state.status_indicator_pid,
            stale=False,
            reachable=reachable,
            state_path=self.state_path,
        )

    def ensure_running(
        self,
        *,
        host: str,
        port: int,
        status_indicator: bool,
    ) -> ServiceStatus:
        current = self.status()
        if current.running:
            return current
        return self.start_background(host=host, port=port, status_indicator=status_indicator)

    def start_background(
        self,
        *,
        host: str = "localhost",
        port: int = 7878,
        status_indicator: bool = True,
    ) -> ServiceStatus:
        current_state = self.load_state()
        if current_state and _is_pid_alive(current_state.pid):
            requested_target_matches = current_state.host == host and current_state.port == port
            if requested_target_matches and _is_port_reachable(current_state.host, current_state.port):
                return self.status()
            _terminate_pid(current_state.pid)
            _terminate_pid(current_state.status_indicator_pid)
            self.clear_state()

        ensure_state_directory()
        command = [
            self.python_executable,
            "-m",
            "whisper_local.cli",
            "bridge",
            "--host",
            host,
            "--port",
            str(port),
            "--capture-logs",
        ]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("ab") as log_handle:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
            )

        if not _wait_for_port(host, port, timeout=SERVICE_READY_TIMEOUT_SECONDS):
            _terminate_pid(process.pid, timeout=1.0)
            raise RuntimeError(f"Service failed to start on {host}:{port}")

        indicator_pid: int | None = None
        if status_indicator and sys.platform == "darwin":
            indicator_provider = create_status_indicator_provider(
                host=host,
                port=port,
                python_executable=self.python_executable,
            )
            try:
                indicator_provider.start()
                indicator_pid = indicator_provider.pid
            except Exception:
                logger.exception("Failed to start status indicator provider")
                indicator_pid = None
                try:
                    indicator_provider.stop()
                except Exception:
                    logger.debug("Failed to clean up status indicator provider after start failure")
                _terminate_pid(process.pid, timeout=1.0)
                self.clear_state()
                raise

        try:
            self.save_state(
                ServiceState.new(
                    pid=process.pid,
                    host=host,
                    port=port,
                    status_indicator_pid=indicator_pid,
                )
            )
        except Exception:
            _terminate_pid(process.pid, timeout=1.0)
            _terminate_pid(indicator_pid, timeout=1.0)
            self.clear_state()
            raise
        return self.status()

    def stop(self) -> ServiceStatus:
        state = self.load_state()
        if state is None:
            return self.status()

        _terminate_pid(state.pid)
        _terminate_pid(state.status_indicator_pid, timeout=1.5)
        self.clear_state()
        return self.status()
