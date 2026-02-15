from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_local import cli


def test_build_parser_creates_parser():
    """Test build_parser creates an ArgumentParser."""
    parser = cli.build_parser()
    assert parser is not None
    assert hasattr(parser, 'parse_args')


def test_build_parser_has_run_command():
    """Test build_parser includes 'run' command."""
    parser = cli.build_parser()
    args = parser.parse_args(['run'])
    assert args.command == 'run'


def test_build_parser_has_bridge_command():
    """Test build_parser includes 'bridge' command."""
    parser = cli.build_parser()
    args = parser.parse_args(['bridge'])
    assert args.command == 'bridge'


def test_build_parser_has_tui_command():
    """Test build_parser includes 'tui' command."""
    parser = cli.build_parser()
    args = parser.parse_args(['tui'])
    assert args.command == 'tui'


def test_build_parser_has_models_command():
    """Test build_parser includes 'models' command."""
    parser = cli.build_parser()
    args = parser.parse_args(['models', 'list'])
    assert args.command == 'models'
    assert args.models_command == 'list'


def test_build_parser_has_config_command():
    """Test build_parser includes 'config' command."""
    parser = cli.build_parser()
    args = parser.parse_args(['config'])
    assert args.command == 'config'


def test_build_parser_run_defaults():
    """Test 'run' command default arguments."""
    parser = cli.build_parser()
    args = parser.parse_args(['run'])
    assert args.host == 'localhost'
    assert args.port == 7878
    assert args.legacy is False
    assert args.no_status_indicator is False


def test_build_parser_run_with_custom_host_port():
    """Test 'run' command with custom host and port."""
    parser = cli.build_parser()
    args = parser.parse_args(['run', '--host', '0.0.0.0', '--port', '8080'])
    assert args.host == '0.0.0.0'
    assert args.port == 8080


def test_build_parser_run_legacy_flag():
    """Test 'run' command with --legacy flag."""
    parser = cli.build_parser()
    args = parser.parse_args(['run', '--legacy'])
    assert args.legacy is True


def test_build_parser_run_no_status_indicator():
    """Test 'run' command with --no-status-indicator flag."""
    parser = cli.build_parser()
    args = parser.parse_args(['run', '--no-status-indicator'])
    assert args.no_status_indicator is True


def test_build_parser_bridge_defaults():
    """Test 'bridge' command default arguments."""
    parser = cli.build_parser()
    args = parser.parse_args(['bridge'])
    assert args.host == 'localhost'
    assert args.port == 7878


def test_build_parser_tui_defaults():
    """Test 'tui' command default arguments."""
    parser = cli.build_parser()
    args = parser.parse_args(['tui'])
    assert args.host == 'localhost'
    assert args.port == 7878


def test_build_parser_models_list():
    """Test 'models list' subcommand."""
    parser = cli.build_parser()
    args = parser.parse_args(['models', 'list'])
    assert args.models_command == 'list'


def test_build_parser_models_pull():
    """Test 'models pull' subcommand."""
    parser = cli.build_parser()
    args = parser.parse_args(['models', 'pull', 'tiny'])
    assert args.models_command == 'pull'
    assert args.name == 'tiny'


def test_build_parser_models_remove():
    """Test 'models remove' subcommand."""
    parser = cli.build_parser()
    args = parser.parse_args(['models', 'remove', 'base'])
    assert args.models_command == 'remove'
    assert args.name == 'base'


def test_build_parser_models_select():
    """Test 'models select' subcommand."""
    parser = cli.build_parser()
    args = parser.parse_args(['models', 'select', 'small'])
    assert args.models_command == 'select'
    assert args.name == 'small'


def test_build_parser_models_set_default_alias():
    """Test 'models set-default' alias for select."""
    parser = cli.build_parser()
    args = parser.parse_args(['models', 'set-default', 'medium'])
    assert args.models_command == 'set-default'
    assert args.name == 'medium'


def test_build_parser_config_with_path():
    """Test 'config' command with --path option."""
    parser = cli.build_parser()
    args = parser.parse_args(['config', '--path', '/custom/config.toml'])
    assert args.path == Path('/custom/config.toml')


def test_build_parser_no_command_defaults_to_none():
    """Test parser with no command sets command to None."""
    parser = cli.build_parser()
    args = parser.parse_args([])
    assert args.command is None


@patch('whisper_local.cli._ensure_runtime_dependencies')
@patch('whisper_local.cli.load_config')
@patch('whisper_local.bridge.run_bridge')
def test_run_bridge_calls_bridge_with_config(mock_run_bridge, mock_load_config, mock_ensure):
    """Test _run_bridge loads config and calls run_bridge."""
    mock_config = Mock()
    mock_load_config.return_value = mock_config

    cli._run_bridge('localhost', 7878)

    mock_ensure.assert_called_once()
    mock_load_config.assert_called_once()
    mock_run_bridge.assert_called_once_with(mock_config, 'localhost', 7878, capture_logs=False)


@patch('whisper_local.cli._ensure_runtime_dependencies')
@patch('whisper_local.cli.load_config')
@patch('whisper_local.bridge.run_bridge')
def test_run_bridge_with_capture_logs(mock_run_bridge, mock_load_config, mock_ensure):
    """Test _run_bridge with capture_logs=True."""
    mock_config = Mock()
    mock_load_config.return_value = mock_config

    cli._run_bridge('localhost', 7878, capture_logs=True)

    mock_ensure.assert_called_once()
    mock_run_bridge.assert_called_once_with(mock_config, 'localhost', 7878, capture_logs=True)


@patch('whisper_local.cli.resolve_tui_runtime')
@patch('whisper_local.cli.subprocess.Popen')
def test_run_tui_starts_tui_process(mock_popen, mock_resolve):
    """Test _run_tui starts TUI subprocess."""
    mock_runtime = Mock()
    mock_runtime.mode = 'packaged'
    mock_runtime.command = ['/usr/bin/tui']
    mock_runtime.cwd = Path('/usr/bin')
    mock_resolve.return_value = mock_runtime

    mock_process = Mock()
    mock_popen.return_value = mock_process

    result = cli._run_tui('localhost', 7878)

    assert result == mock_process
    mock_resolve.assert_called_once()
    mock_popen.assert_called_once_with(
        ['/usr/bin/tui', '--host', 'localhost', '--port', '7878'],
        cwd='/usr/bin'
    )


@patch('whisper_local.cli.sys.platform', 'darwin')
@patch('whisper_local.cli.subprocess.Popen')
def test_start_status_indicator_on_macos(mock_popen):
    """Test _start_status_indicator starts process on macOS."""
    mock_process = Mock()
    mock_popen.return_value = mock_process

    result = cli._start_status_indicator('localhost', 7878)

    assert result == mock_process
    args = mock_popen.call_args[0][0]
    assert '-m' in args
    assert 'whisper_local.status_indicator' in args


@patch('whisper_local.cli.sys.platform', 'linux')
def test_start_status_indicator_on_non_macos():
    """Test _start_status_indicator returns None on non-macOS."""
    result = cli._start_status_indicator('localhost', 7878)
    assert result is None


@patch('whisper_local.cli.sys.platform', 'darwin')
@patch('whisper_local.cli.subprocess.Popen')
def test_start_status_indicator_handles_error(mock_popen):
    """Test _start_status_indicator returns None on error."""
    mock_popen.side_effect = Exception("Failed to start")

    result = cli._start_status_indicator('localhost', 7878)
    assert result is None


@patch('whisper_local.cli.sys.stdout')
@patch('whisper_local.cli.sys.stdin')
def test_restore_terminal_state_when_tty(mock_stdin, mock_stdout):
    """Test _restore_terminal_state restores terminal when TTY."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True

    cli._restore_terminal_state()

    mock_stdout.write.assert_called()
    mock_stdout.flush.assert_called()


@patch('whisper_local.cli.sys.stdout')
@patch('whisper_local.cli.sys.stdin')
def test_restore_terminal_state_when_not_tty(mock_stdin, mock_stdout):
    """Test _restore_terminal_state skips when not TTY."""
    mock_stdin.isatty.return_value = False
    mock_stdout.isatty.return_value = False

    cli._restore_terminal_state()

    mock_stdout.write.assert_not_called()


@patch('whisper_local.cli._run_bridge')
def test_main_runs_bridge_command(mock_run_bridge, monkeypatch):
    """Test main handles 'bridge' command."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'bridge', '--host', '127.0.0.1', '--port', '9000'])

    cli.main()

    mock_run_bridge.assert_called_once_with('127.0.0.1', 9000)


@patch('whisper_local.cli._run_tui')
@patch('whisper_local.cli._restore_terminal_state')
def test_main_runs_tui_command(mock_restore, mock_run_tui, monkeypatch):
    """Test main handles 'tui' command."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'tui'])

    mock_process = Mock()
    mock_process.wait.return_value = None
    mock_run_tui.return_value = mock_process

    cli.main()

    mock_run_tui.assert_called_once()
    mock_process.wait.assert_called_once()
    mock_restore.assert_called_once()


@patch('whisper_local.cli._run_tui')
@patch('whisper_local.cli._restore_terminal_state')
def test_main_tui_handles_keyboard_interrupt(mock_restore, mock_run_tui, monkeypatch):
    """Test main handles KeyboardInterrupt in 'tui' command."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'tui'])

    mock_process = Mock()
    mock_process.wait.side_effect = KeyboardInterrupt()
    mock_run_tui.return_value = mock_process

    # Should not raise
    cli.main()

    mock_restore.assert_called_once()


@patch('whisper_local.model_manager.list_installed_models')
def test_main_models_list(mock_list_models, monkeypatch, capsys):
    """Test main handles 'models list' command."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'models', 'list'])

    mock_model1 = Mock(installed=True)
    mock_model1.name = 'tiny'
    mock_model2 = Mock(installed=False)
    mock_model2.name = 'base'
    mock_list_models.return_value = [mock_model1, mock_model2]

    cli.main()

    captured = capsys.readouterr()
    assert 'tiny: installed' in captured.out
    assert 'base: available' in captured.out


@patch('whisper_local.model_manager.download_model')
def test_main_models_pull(mock_download, monkeypatch, capsys):
    """Test main handles 'models pull' command."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'models', 'pull', 'small'])

    cli.main()

    mock_download.assert_called_once_with('small')
    captured = capsys.readouterr()
    assert 'Downloaded small' in captured.out


@patch('whisper_local.model_manager.remove_model')
def test_main_models_remove(mock_remove, monkeypatch, capsys):
    """Test main handles 'models remove' command."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'models', 'remove', 'medium'])

    cli.main()

    mock_remove.assert_called_once_with('medium')
    captured = capsys.readouterr()
    assert 'Removed medium' in captured.out


@patch('whisper_local.model_manager.set_selected_model')
def test_main_models_select(mock_set_selected, monkeypatch, capsys):
    """Test main handles 'models select' command."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'models', 'select', 'large-v3'])

    cli.main()

    mock_set_selected.assert_called_once_with('large-v3')
    captured = capsys.readouterr()
    assert 'Selected model set to large-v3' in captured.out


@patch('whisper_local.model_manager.set_selected_model')
def test_main_models_set_default(mock_set_selected, monkeypatch, capsys):
    """Test main handles 'models set-default' command (alias)."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'models', 'set-default', 'tiny'])

    cli.main()

    mock_set_selected.assert_called_once_with('tiny')


@patch('whisper_local.cli.load_config')
def test_main_config_command(mock_load_config, monkeypatch, capsys):
    """Test main handles 'config' command."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'config'])

    mock_config = Mock()
    mock_config.to_dict.return_value = {
        'model': {'name': 'tiny', 'backend': 'faster-whisper'},
        'audio': {'sample_rate': 16000},
        'simple_value': 'test'
    }
    mock_load_config.return_value = mock_config

    cli.main()

    captured = capsys.readouterr()
    assert '[model]' in captured.out
    assert 'name = tiny' in captured.out
    assert '[audio]' in captured.out
    assert 'simple_value = test' in captured.out


@patch('whisper_local.cli._run_combined')
def test_main_no_command_defaults_to_run(mock_run_combined, monkeypatch):
    """Test main with no command defaults to 'run'."""
    monkeypatch.setattr(sys, 'argv', ['cli'])

    cli.main()

    mock_run_combined.assert_called_once_with('localhost', 7878, status_indicator=True)


@patch('whisper_local.cli._run_combined')
def test_main_run_command_without_legacy(mock_run_combined, monkeypatch):
    """Test main 'run' command without --legacy flag."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'run'])

    cli.main()

    mock_run_combined.assert_called_once_with('localhost', 7878, status_indicator=True)


@patch('whisper_local.tui.run_app')
def test_main_run_command_with_legacy(mock_run_app, monkeypatch):
    """Test main 'run' command with --legacy flag."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'run', '--legacy'])

    cli.main()

    mock_run_app.assert_called_once()


@patch('whisper_local.cli._run_combined')
def test_main_run_with_no_status_indicator(mock_run_combined, monkeypatch):
    """Test main 'run' command with --no-status-indicator."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'run', '--no-status-indicator'])

    cli.main()

    mock_run_combined.assert_called_once_with('localhost', 7878, status_indicator=False)


@patch('whisper_local.cli._run_tui')
@patch('whisper_local.cli._restore_terminal_state')
def test_main_tui_file_not_found_exits(mock_restore, mock_run_tui, monkeypatch, capsys):
    """Test main exits with error when TUI binary not found."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'tui'])

    mock_process = Mock()
    mock_process.wait.side_effect = FileNotFoundError("TUI binary not found")
    mock_run_tui.return_value = mock_process

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert 'Error:' in captured.out


@patch('whisper_local.cli.load_config')
def test_ensure_runtime_dependencies_called(mock_load_config):
    """Test _ensure_runtime_dependencies is called appropriately."""
    # This is tested implicitly through other tests
    # Just verify the function exists
    assert hasattr(cli, '_ensure_runtime_dependencies')


def test_prog_name_uses_argv():
    """Test build_parser uses sys.argv[0] for program name."""
    with patch.object(sys, 'argv', ['/usr/bin/whisper-local']):
        parser = cli.build_parser()
        assert 'whisper-local' in parser.prog


def test_config_prints_nested_dict_values(monkeypatch, capsys):
    """Test config command prints nested dictionary values correctly."""
    monkeypatch.setattr(sys, 'argv', ['cli', 'config'])

    with patch('whisper_local.cli.load_config') as mock_load_config:
        mock_config = Mock()
        mock_config.to_dict.return_value = {
            'output': {'file': {'enabled': True, 'path': '/tmp/output.txt'}},
        }
        mock_load_config.return_value = mock_config

        cli.main()

        captured = capsys.readouterr()
        assert '[output]' in captured.out
        assert 'file.enabled = True' in captured.out
        assert 'file.path = /tmp/output.txt' in captured.out
