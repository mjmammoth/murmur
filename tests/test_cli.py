from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_local import cli
from whisper_local.uninstall import (
    RemovalFailure,
    UninstallActionRequired,
    UninstallError,
    UninstallOptions,
    UninstallResult,
)
from whisper_local.upgrade import UpgradeActionRequired, UpgradeError, UpgradeResult


def test_build_parser_includes_start_command() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["start"])
    assert args.command == "start"


def test_build_parser_includes_trigger_command() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["trigger", "toggle"])
    assert args.command == "trigger"
    assert args.action == "toggle"
    assert args.timeout_seconds == 3.0


def test_build_parser_includes_upgrade_command() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["upgrade", "--version", "v1.2.3"])
    assert args.command == "upgrade"
    assert args.version == "v1.2.3"


def test_build_parser_includes_uninstall_command() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["uninstall", "--yes", "--all-data"])
    assert args.command == "uninstall"
    assert args.yes is True
    assert args.all_data is True


def test_build_parser_includes_version_command() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["version"])
    assert args.command == "version"


def test_build_parser_tui_defaults() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["tui"])
    assert args.host == "localhost"
    assert args.port == 7878


def test_build_parser_start_defaults() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["start"])
    assert args.host == "localhost"
    assert args.port == 7878
    assert args.foreground is False


def test_build_parser_rejects_removed_service_command() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["service", "status"])
    assert exc_info.value.code == 2


def test_main_rejects_removed_service_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "service", "status"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2


def test_build_parser_models_pull_with_runtime() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["models", "pull", "tiny", "--runtime", "whisper.cpp"])
    assert args.command == "models"
    assert args.models_command == "pull"
    assert args.runtime == "whisper.cpp"


@patch("whisper_local.cli.load_config")
@patch("whisper_local.bridge.run_bridge")
def test_run_bridge_calls_bridge_with_config(mock_run_bridge: Mock, mock_load_config: Mock) -> None:
    mock_config = Mock()
    mock_load_config.return_value = mock_config

    cli._run_bridge("localhost", 7878, capture_logs=True)

    mock_load_config.assert_called_once()
    mock_run_bridge.assert_called_once_with(mock_config, "localhost", 7878, capture_logs=True)


@patch("whisper_local.cli.resolve_tui_runtime")
@patch("whisper_local.cli.subprocess.Popen")
def test_run_tui_starts_tui_process(mock_popen: Mock, mock_resolve: Mock) -> None:
    runtime = Mock()
    runtime.mode = "packaged"
    runtime.command = ["/usr/bin/tui"]
    runtime.cwd = Path("/usr/bin")
    mock_resolve.return_value = runtime

    process = Mock()
    mock_popen.return_value = process

    result = cli._run_tui("localhost", 7878)

    assert result == process
    mock_popen.assert_called_once_with(
        ["/usr/bin/tui", "--host", "localhost", "--port", "7878"],
        cwd="/usr/bin",
    )


@patch("whisper_local.cli.sys.stdout")
@patch("whisper_local.cli.sys.stdin")
def test_restore_terminal_state_when_tty(mock_stdin: Mock, mock_stdout: Mock) -> None:
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True

    cli._restore_terminal_state()

    mock_stdout.write.assert_called()
    mock_stdout.flush.assert_called()


@patch("whisper_local.cli.sys.stdout")
@patch("whisper_local.cli.sys.stdin")
def test_restore_terminal_state_when_not_tty(mock_stdin: Mock, mock_stdout: Mock) -> None:
    mock_stdin.isatty.return_value = False
    mock_stdout.isatty.return_value = False

    cli._restore_terminal_state()

    mock_stdout.write.assert_not_called()


@patch("whisper_local.cli._ensure_service_running")
@patch("whisper_local.cli._run_tui")
@patch("whisper_local.cli._restore_terminal_state")
def test_run_tui_attach_auto_starts_service(
    mock_restore: Mock,
    mock_run_tui: Mock,
    mock_ensure_service: Mock,
) -> None:
    process = Mock()
    mock_run_tui.return_value = process
    service_status = Mock()
    service_status.host = "127.0.0.1"
    service_status.port = 9000
    mock_ensure_service.return_value = service_status

    cli._run_tui_attach("localhost", 7878, status_indicator=True)

    mock_ensure_service.assert_called_once_with("localhost", 7878, status_indicator=True)
    mock_run_tui.assert_called_once_with("127.0.0.1", 9000)
    process.wait.assert_called_once()
    mock_restore.assert_called_once()


@patch("whisper_local.cli._run_bridge")
@patch("whisper_local.cli.create_status_indicator_provider")
def test_service_run_foreground_without_status_indicator_skips_indicator_provider(
    mock_create_indicator_provider: Mock,
    mock_run_bridge: Mock,
) -> None:
    cli._service_run("localhost", 7878, foreground=True, status_indicator=False)

    mock_create_indicator_provider.assert_not_called()
    mock_run_bridge.assert_called_once_with("localhost", 7878, capture_logs=True)


@patch("whisper_local.cli.logger")
@patch("whisper_local.cli._run_bridge")
@patch("whisper_local.cli.create_status_indicator_provider")
def test_service_run_foreground_stops_indicator_after_successful_start(
    mock_create_indicator_provider: Mock,
    mock_run_bridge: Mock,
    mock_logger: Mock,
) -> None:
    indicator_provider = Mock()
    mock_create_indicator_provider.return_value = indicator_provider

    cli._service_run("localhost", 7878, foreground=True, status_indicator=True)

    mock_create_indicator_provider.assert_called_once_with(host="localhost", port=7878)
    indicator_provider.start.assert_called_once()
    indicator_provider.stop.assert_called_once()
    mock_logger.warning.assert_not_called()
    mock_run_bridge.assert_called_once_with("localhost", 7878, capture_logs=True)


@patch("whisper_local.cli.logger")
@patch("whisper_local.cli._run_bridge")
@patch("whisper_local.cli.create_status_indicator_provider")
def test_service_run_foreground_does_not_stop_indicator_when_start_fails(
    mock_create_indicator_provider: Mock,
    mock_run_bridge: Mock,
    mock_logger: Mock,
) -> None:
    indicator_provider = Mock()
    indicator_provider.start.side_effect = RuntimeError("indicator start failed")
    mock_create_indicator_provider.return_value = indicator_provider

    cli._service_run("localhost", 7878, foreground=True, status_indicator=True)

    indicator_provider.start.assert_called_once()
    indicator_provider.stop.assert_not_called()
    mock_logger.warning.assert_called_once()
    mock_run_bridge.assert_called_once_with("localhost", 7878, capture_logs=True)


@patch("whisper_local.cli._ensure_service_running", side_effect=RuntimeError("boom"))
def test_run_tui_attach_exits_when_service_start_fails(mock_ensure_service: Mock, capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli._run_tui_attach("localhost", 7878, status_indicator=True)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "failed to start service" in captured.out
    mock_ensure_service.assert_called_once()


@patch("whisper_local.cli._service_run")
def test_main_no_command_prints_help(
    mock_service_run: Mock,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(sys, "argv", ["cli"])

    cli.main()

    mock_service_run.assert_not_called()
    captured = capsys.readouterr()
    assert "usage:" in captured.out


@patch("whisper_local.cli._run_tui_attach")
def test_main_run_command_uses_tui_attach(mock_attach: Mock, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "run", "--host", "127.0.0.1", "--port", "9000"])

    cli.main()

    mock_attach.assert_called_once_with("127.0.0.1", 9000, status_indicator=True)
    captured = capsys.readouterr()
    assert "deprecated" in captured.err.lower()


@patch("whisper_local.cli._run_bridge")
def test_main_runs_bridge_command(mock_run_bridge: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "bridge", "--host", "127.0.0.1", "--port", "9000"])

    cli.main()

    mock_run_bridge.assert_called_once_with("127.0.0.1", 9000, capture_logs=False)


@patch("whisper_local.cli._run_tui_attach")
def test_main_runs_tui_command(mock_attach: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "tui", "--no-status-indicator"])

    cli.main()

    mock_attach.assert_called_once_with("localhost", 7878, status_indicator=False)


@patch("whisper_local.cli._service_run")
def test_main_start_command_defaults_to_background_service(
    mock_service_run: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "start"])

    cli.main()

    mock_service_run.assert_called_once_with("localhost", 7878, foreground=False, status_indicator=True)


@patch("whisper_local.cli._service_run")
def test_main_start_command(mock_service_run: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli", "start", "--host", "0.0.0.0", "--port", "8123", "--foreground", "--no-status-indicator"],
    )

    cli.main()

    mock_service_run.assert_called_once_with("0.0.0.0", 8123, foreground=True, status_indicator=False)


@patch("whisper_local.cli._service_stop")
def test_main_stop_command(mock_service_stop: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "stop"])

    cli.main()

    mock_service_stop.assert_called_once()


@patch("whisper_local.cli._service_status")
def test_main_status_command(mock_service_status: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "status"])

    cli.main()

    mock_service_status.assert_called_once()


@patch("whisper_local.cli._trigger")
def test_main_trigger_command(mock_trigger: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "trigger", "toggle"])

    cli.main()

    mock_trigger.assert_called_once_with(
        "localhost",
        7878,
        action="toggle",
        status_indicator=True,
        timeout_seconds=3.0,
    )


@patch("whisper_local.cli._trigger")
def test_main_trigger_command_with_custom_timeout(
    mock_trigger: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "trigger", "start", "--timeout-seconds", "5.5"])

    cli.main()

    mock_trigger.assert_called_once_with(
        "localhost",
        7878,
        action="start",
        status_indicator=True,
        timeout_seconds=5.5,
    )


@patch("whisper_local.cli._ensure_service_running")
@patch("whisper_local.cli.asyncio.run")
def test_trigger_success_prints_ack(
    mock_asyncio_run: Mock,
    mock_ensure_service: Mock,
    capsys,
) -> None:
    service_status = Mock()
    service_status.host = "127.0.0.1"
    service_status.port = 9000
    mock_ensure_service.return_value = service_status

    def _runner(coro):
        coro.close()
        return "recording"

    mock_asyncio_run.side_effect = _runner

    cli._trigger(
        "localhost",
        7878,
        action="start",
        status_indicator=True,
        timeout_seconds=3.0,
    )

    mock_ensure_service.assert_called_once_with("localhost", 7878, status_indicator=True)
    captured = capsys.readouterr()
    assert "Trigger acknowledged: status=recording" in captured.out


@patch("whisper_local.cli._ensure_service_running")
@patch("whisper_local.cli._trigger_async")
def test_trigger_uses_resolved_service_endpoint(
    mock_trigger_async: Mock,
    mock_ensure_service: Mock,
    capsys,
) -> None:
    service_status = Mock()
    service_status.host = "127.0.0.1"
    service_status.port = 9000
    mock_ensure_service.return_value = service_status
    mock_trigger_async.return_value = "ready"

    cli._trigger(
        "localhost",
        7878,
        action="start",
        status_indicator=True,
        timeout_seconds=3.0,
    )

    mock_trigger_async.assert_called_once_with("127.0.0.1", 9000, "start", 3.0)
    captured = capsys.readouterr()
    assert "Trigger acknowledged: status=ready" in captured.out


@patch("whisper_local.cli._ensure_service_running")
@patch("whisper_local.cli.asyncio.run")
def test_trigger_timeout_exits_non_zero(
    mock_asyncio_run: Mock,
    mock_ensure_service: Mock,
    capsys,
) -> None:
    service_status = Mock()
    service_status.host = "127.0.0.1"
    service_status.port = 9000
    mock_ensure_service.return_value = service_status

    def _runner(coro):
        coro.close()
        raise TimeoutError("ack timeout")

    mock_asyncio_run.side_effect = _runner

    with pytest.raises(SystemExit) as exc_info:
        cli._trigger(
            "localhost",
            7878,
            action="stop",
            status_indicator=True,
            timeout_seconds=1.0,
        )

    assert exc_info.value.code == 2
    mock_ensure_service.assert_called_once_with("localhost", 7878, status_indicator=True)
    captured = capsys.readouterr()
    assert "timed out" in captured.out


@patch("whisper_local.cli._ensure_service_running")
@patch("whisper_local.cli.asyncio.run")
def test_trigger_error_exits_non_zero(
    mock_asyncio_run: Mock,
    mock_ensure_service: Mock,
    capsys,
) -> None:
    service_status = Mock()
    service_status.host = "127.0.0.1"
    service_status.port = 9000
    mock_ensure_service.return_value = service_status

    def _runner(coro):
        coro.close()
        raise RuntimeError("ws error")

    mock_asyncio_run.side_effect = _runner

    with pytest.raises(SystemExit) as exc_info:
        cli._trigger(
            "localhost",
            7878,
            action="start",
            status_indicator=True,
            timeout_seconds=1.0,
        )

    assert exc_info.value.code == 1
    mock_ensure_service.assert_called_once_with("localhost", 7878, status_indicator=True)
    captured = capsys.readouterr()
    assert "trigger command failed" in captured.out


@patch("whisper_local.cli._upgrade")
def test_main_upgrade_command(mock_upgrade: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "upgrade", "--version", "v2.0.0"])

    cli.main()

    mock_upgrade.assert_called_once_with(requested_version="v2.0.0")


@patch("whisper_local.cli._uninstall")
def test_main_uninstall_command(mock_uninstall: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "uninstall", "--yes"])

    cli.main()

    mock_uninstall.assert_called_once()


def test_main_version_flag_prints_and_exits(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli, "__version__", "9.9.9")
    monkeypatch.setattr(sys, "argv", ["cli", "--version"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "9.9.9" in captured.out


@patch("whisper_local.cli._print_version")
def test_main_version_command(mock_print_version: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "version"])

    cli.main()

    mock_print_version.assert_called_once()


def test_print_version_outputs_installed_version(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "__version__", "1.2.3")
    cli._print_version()
    captured = capsys.readouterr()
    assert captured.out.strip() == "1.2.3"


@patch("whisper_local.uninstall.run_uninstall")
@patch("whisper_local.cli.sys.stdout")
@patch("whisper_local.cli.sys.stdin")
def test_uninstall_non_interactive_without_flags_requires_yes(
    mock_stdin: Mock,
    mock_stdout: Mock,
    mock_run_uninstall: Mock,
    capsys,
) -> None:
    mock_stdin.isatty.return_value = False
    mock_stdout.isatty.return_value = False
    parser = cli.build_parser()
    args = parser.parse_args(["uninstall"])

    with pytest.raises(SystemExit) as exc_info:
        cli._uninstall(args)

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "non-interactive uninstall requires --yes" in captured.err
    mock_run_uninstall.assert_not_called()


@patch("whisper_local.uninstall.run_uninstall")
@patch("builtins.input", side_effect=["2", "y"])
@patch("whisper_local.cli.sys.stdout")
@patch("whisper_local.cli.sys.stdin")
def test_uninstall_interactive_prompt_selects_scope(
    mock_stdin: Mock,
    mock_stdout: Mock,
    mock_input: Mock,
    mock_run_uninstall: Mock,
) -> None:
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True
    parser = cli.build_parser()
    args = parser.parse_args(["uninstall"])
    mock_run_uninstall.return_value = UninstallResult(
        channel="installer",
        removed_paths=(),
        failed_paths=(),
        warnings=(),
    )

    cli._uninstall(args)

    mock_run_uninstall.assert_called_once_with(
        options=UninstallOptions(
            remove_state=True,
            remove_config=True,
            remove_model_cache=False,
        )
    )


@patch("whisper_local.uninstall.run_uninstall")
def test_uninstall_success_outputs_summary(mock_run_uninstall: Mock, capsys) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["uninstall", "--yes"])
    mock_run_uninstall.return_value = UninstallResult(
        channel="installer",
        removed_paths=(Path("/tmp/a"), Path("/tmp/b")),
        failed_paths=(),
        warnings=("warn",),
    )

    cli._uninstall(args)

    captured = capsys.readouterr()
    assert "Removed paths:" in captured.out
    assert "Warnings:" in captured.out
    assert "Uninstall complete." in captured.out


@patch("whisper_local.uninstall.run_uninstall")
def test_uninstall_action_required_exits_with_guidance(mock_run_uninstall: Mock, capsys) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["uninstall", "--yes"])
    mock_run_uninstall.side_effect = UninstallActionRequired(
        channel="homebrew",
        command="brew uninstall whisper-local",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli._uninstall(args)

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "brew uninstall whisper-local" in captured.out


@patch("whisper_local.uninstall.run_uninstall")
def test_uninstall_error_exits_non_zero(mock_run_uninstall: Mock, capsys) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["uninstall", "--yes"])
    mock_run_uninstall.side_effect = UninstallError("failed")

    with pytest.raises(SystemExit) as exc_info:
        cli._uninstall(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: failed" in captured.out


@patch("whisper_local.uninstall.run_uninstall")
def test_uninstall_reports_failed_paths_as_non_zero(mock_run_uninstall: Mock, capsys) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["uninstall", "--yes"])
    mock_run_uninstall.return_value = UninstallResult(
        channel="installer",
        removed_paths=(Path("/tmp/a"),),
        failed_paths=(RemovalFailure(path=Path("/tmp/b"), reason="permission denied"),),
        warnings=(),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli._uninstall(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Failed to remove:" in captured.out


@patch("whisper_local.upgrade.run_upgrade")
def test_upgrade_success_output(mock_run_upgrade: Mock, capsys) -> None:
    mock_run_upgrade.return_value = UpgradeResult(
        channel="installer",
        tag="v1.2.0",
        previous_version="1.1.0",
        new_version="1.2.0",
        restarted_service=True,
    )

    cli._upgrade(requested_version="v1.2.0")

    captured = capsys.readouterr()
    assert "1.1.0 -> 1.2.0" in captured.out
    assert "restarted" in captured.out


@patch("whisper_local.upgrade.run_upgrade")
def test_upgrade_action_required_exits_with_guidance(mock_run_upgrade: Mock, capsys) -> None:
    mock_run_upgrade.side_effect = UpgradeActionRequired(
        channel="homebrew",
        command="brew update && brew upgrade whisper-local",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli._upgrade(requested_version=None)

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "brew upgrade whisper-local" in captured.out


@patch("whisper_local.upgrade.run_upgrade", side_effect=UpgradeError("network error"))
def test_upgrade_error_exits_non_zero(mock_run_upgrade: Mock, capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli._upgrade(requested_version=None)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "network error" in captured.out


@patch("whisper_local.model_manager.list_installed_models")
def test_main_models_list_runtime_variants(mock_list_models: Mock, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "models", "list"])

    model = Mock()
    model.name = "small"
    model.variants = {
        "faster-whisper": Mock(installed=True),
        "whisper.cpp": Mock(installed=False),
    }
    mock_list_models.return_value = [model]

    cli.main()

    captured = capsys.readouterr()
    assert "small: faster-whisper=installed, whisper.cpp=available" in captured.out


def test_main_models_without_subcommand_exits_with_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "models"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "No subcommand provided for 'models'" in captured.err


@patch("whisper_local.cli.load_config")
def test_main_config_command(mock_load_config: Mock, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "config"])

    mock_config = Mock()
    mock_config.to_dict.return_value = {
        "model": {"name": "tiny", "runtime": "faster-whisper"},
        "history": {"max_entries": 5000},
    }
    mock_load_config.return_value = mock_config

    cli.main()

    captured = capsys.readouterr()
    assert "[model]" in captured.out
    assert "[history]" in captured.out


def test_prog_name_uses_argv() -> None:
    with patch.object(sys, "argv", ["/usr/bin/whisper-local"]):
        parser = cli.build_parser()
        assert "whisper-local" in parser.prog


@patch("whisper_local.cli.ServiceManager")
def test_ensure_service_running_returns_service_status(mock_service_manager: Mock) -> None:
    expected_status = Mock()
    manager_instance = mock_service_manager.return_value
    manager_instance.ensure_running.return_value = expected_status

    result = cli._ensure_service_running("localhost", 7878, status_indicator=True)

    assert result is expected_status
    manager_instance.ensure_running.assert_called_once_with(
        host="localhost",
        port=7878,
        status_indicator=True,
    )


def test_wait_for_status_ignores_non_object_json_payloads() -> None:
    class DummyWebSocket:
        def __init__(self) -> None:
            self._messages = [
                "[]",
                '"string-payload"',
                '{"type":"status","status":"ready","message":"Ready"}',
            ]

        async def recv(self) -> str:
            if not self._messages:
                raise TimeoutError
            return self._messages.pop(0)

    status, message = asyncio.run(
        cli._wait_for_status(
            DummyWebSocket(),
            timeout_seconds=1.0,
        )
    )

    assert status == "ready"
    assert message == "Ready"
