from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from whisper_local.config import SUPPORTED_RUNTIMES, load_config
from whisper_local.tui_runtime import resolve_tui_runtime


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
WHISPER_CPP_BINARIES = ("whisper-cli", "whisper-cpp", "main")


def build_parser() -> argparse.ArgumentParser:
    """
    Builds the top-level command-line argument parser for the application.
    
    The parser includes these subcommands:
    - run: start the combined bridge and TypeScript TUI (with options for host, port, and disabling the macOS status indicator).
    - bridge: start only the WebSocket bridge (host and port options).
    - tui: start only the TypeScript TUI (host and port options).
    - models: manage models with subcommands `list`, `pull <name>`, `remove <name>`, and `select|set-default <name>`.
    - config: show configuration (optional --path).
    
    Returns:
        argparse.ArgumentParser: A configured parser ready to parse the application's CLI.
    """
    parser = argparse.ArgumentParser(prog=(Path(sys.argv[0]).name or "whisper.local"))
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the TUI (bridge + TypeScript frontend)")
    run_parser.add_argument("--host", default="localhost", help="Bridge host")
    run_parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    run_parser.add_argument(
        "--no-status-indicator",
        action="store_true",
        help="Disable macOS menu bar status indicator",
    )

    bridge_parser = subparsers.add_parser("bridge", help="Start only the WebSocket bridge server")
    bridge_parser.add_argument("--host", default="localhost", help="Bridge host")
    bridge_parser.add_argument("--port", type=int, default=7878, help="Bridge port")

    tui_parser = subparsers.add_parser("tui", help="Start only the TypeScript TUI (requires bridge)")
    tui_parser.add_argument("--host", default="localhost", help="Bridge host")
    tui_parser.add_argument("--port", type=int, default=7878, help="Bridge port")

    models_parser = subparsers.add_parser("models", help="Manage models")
    models_sub = models_parser.add_subparsers(dest="models_command")
    models_sub.add_parser("list", help="List available models")

    pull_parser = models_sub.add_parser("pull", help="Download a model")
    pull_parser.add_argument("name")
    pull_parser.add_argument(
        "--runtime",
        choices=SUPPORTED_RUNTIMES,
        default="faster-whisper",
        help="Model runtime variant to download",
    )

    remove_parser = models_sub.add_parser("remove", help="Remove a model")
    remove_parser.add_argument("name")
    remove_parser.add_argument(
        "--runtime",
        choices=SUPPORTED_RUNTIMES,
        default="faster-whisper",
        help="Model runtime variant to remove",
    )

    select_parser = models_sub.add_parser(
        "select",
        aliases=["set-default"],
        help="Select model",
    )
    select_parser.add_argument("name")

    config_parser = subparsers.add_parser("config", help="Show config")
    config_parser.add_argument("--path", type=Path)

    return parser


def _ensure_runtime_dependencies() -> None:
    """
    Ensure required runtime dependencies for local speech transcription are installed.
    
    If verification fails, prints the error message and exits the process with status code 1.
    """
    for binary in WHISPER_CPP_BINARIES:
        if shutil.which(binary) is not None:
            return
    print("Error: whisper.cpp is required but not installed. Install with: brew install whisper-cpp")
    sys.exit(1)


def _run_bridge(host: str, port: int, capture_logs: bool = False) -> None:
    """Run the bridge server."""
    _ensure_runtime_dependencies()
    from whisper_local.bridge import run_bridge
    config = load_config()
    run_bridge(config, host, port, capture_logs=capture_logs)


def _run_tui(host: str, port: int) -> subprocess.Popen:
    """
    Start the external TUI process using the resolved TUI runtime and bind it to the given host and port.
    
    Returns:
        subprocess.Popen: The subprocess running the TUI.
    """
    runtime = resolve_tui_runtime(cli_file=__file__)
    logger.info("Starting TUI runtime mode=%s", runtime.mode)
    cmd = [*runtime.command, "--host", host, "--port", str(port)]
    return subprocess.Popen(cmd, cwd=str(runtime.cwd) if runtime.cwd else None)


def _start_status_indicator(host: str, port: int) -> subprocess.Popen | None:
    """
    Start the macOS menu bar status indicator sidecar.
    
    Attempts to launch the status indicator as a subprocess and returns the process handle. If the current platform is not macOS or the process fails to start, returns `None`.
     
    Returns:
        subprocess.Popen: The started status indicator process.
        `None` if the indicator was not started (for example, not running on macOS or process launch failed).
    """
    if sys.platform != "darwin":
        return None

    cmd = [
        sys.executable,
        "-m",
        "whisper_local.status_indicator",
        "--host",
        host,
        "--port",
        str(port),
    ]
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None


def _restore_terminal_state() -> None:
    """Best-effort terminal recovery in parent process."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return

    try:
        # Disable common mouse tracking modes, restore cursor, and reset attributes.
        sys.stdout.write("\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l\x1b[?25h\x1b[0m")
        sys.stdout.flush()
    except Exception:
        pass

    try:
        subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass


def _run_combined(host: str, port: int, status_indicator: bool = True) -> None:
    """
    Start and coordinate the bridge server and the TypeScript TUI, managing their lifecycle and cleanup.
    
    Starts the bridge in a background thread, launches the TUI as a subprocess, optionally starts the platform status indicator (macOS only), and ensures graceful shutdown, error handling, and terminal state restoration on exit.
    
    Parameters:
        host (str): Network interface or hostname used by both the bridge and the TUI.
        port (int): TCP port used by both the bridge and the TUI.
        status_indicator (bool): If True, attempt to start the platform status indicator; may be ignored on non‑macOS platforms.
    """
    _ensure_runtime_dependencies()

    # Validate config early, before we suppress stderr
    try:
        config = load_config()
    except Exception as e:
        print(f"Error loading config: {e}")
        sys.exit(1)

    # Capture the real stderr before redirecting, so we can restore it on fatal errors
    real_stderr = sys.stderr

    # Suppress all stderr/stdout from the bridge thread - the TUI owns the terminal.
    # Logs are routed through WebSocket and displayed in the TUI's log panel.
    logging.getLogger().handlers.clear()
    logging.getLogger().addHandler(logging.NullHandler())

    # Redirect Python's stderr to devnull so stray prints don't corrupt the TUI
    devnull = open(os.devnull, "w")
    sys.stderr = devnull

    # Track bridge state/errors
    bridge_server = None
    bridge_error: list[Exception] = []
    status_indicator_process: subprocess.Popen | None = None
    tui_process: subprocess.Popen | None = None
    interrupted = False
    previous_sigint = signal.getsignal(signal.SIGINT)

    def _bridge_target() -> None:
        nonlocal bridge_server
        try:
            from whisper_local.bridge import BridgeServer

            bridge_server = BridgeServer(config)
            asyncio.run(bridge_server.start(host, port, capture_logs=True))
        except Exception as e:
            bridge_error.append(e)
        finally:
            if bridge_server is not None:
                bridge_server.shutdown()

    # Start bridge in a thread with log capture enabled
    bridge_thread = threading.Thread(target=_bridge_target, daemon=True)
    bridge_thread.start()

    # Wait for bridge to start, checking for early failures
    time.sleep(0.5)

    if bridge_error:
        sys.stderr = real_stderr
        print(f"Bridge failed to start: {bridge_error[0]}", file=real_stderr)
        sys.exit(1)

    if status_indicator:
        status_indicator_process = _start_status_indicator(host, port)

    # Start TUI
    try:
        tui_process = _run_tui(host, port)
        tui_process.wait()
    except KeyboardInterrupt:
        interrupted = True
    except FileNotFoundError as e:
        sys.stderr = real_stderr
        print(f"Error: {e}", file=real_stderr)
        sys.exit(1)
    finally:
        if interrupted:
            try:
                signal.signal(signal.SIGINT, signal.SIG_IGN)
            except Exception:
                pass

        if tui_process is not None and tui_process.poll() is None:
            tui_process.terminate()
            try:
                tui_process.wait(timeout=1.0)
            except Exception:
                try:
                    tui_process.kill()
                except Exception:
                    pass

        if status_indicator_process is not None:
            status_indicator_process.terminate()
            try:
                status_indicator_process.wait(timeout=1.0)
            except Exception:
                pass

        if bridge_server is not None:
            bridge_server.shutdown()
            bridge_thread.join(timeout=2.5)
            if bridge_thread.is_alive():
                logger.warning("Bridge thread still alive after graceful shutdown window; forcing loop stop")
                loop = bridge_server._loop
                if loop and not loop.is_closed():
                    loop.call_soon_threadsafe(loop.stop)
                bridge_thread.join(timeout=1.5)
                if bridge_thread.is_alive():
                    logger.warning("Bridge thread still alive after forced loop stop")
        else:
            bridge_thread.join(timeout=1.0)

        sys.stderr = real_stderr
        _restore_terminal_state()
        devnull.close()
        if interrupted:
            try:
                signal.signal(signal.SIGINT, previous_sigint)
            except Exception:
                pass


def main() -> None:
    """
    Parse CLI arguments and dispatch the selected subcommand to run the application's components.
    
    Recognizes these subcommands:
    - run (default): start the TypeScript TUI stack (supports host, port, and status-indicator toggle).
    - bridge: start the bridge server on a given host and port.
    - tui: start the TUI subprocess and wait for it; restores terminal state on exit.
    - models: manage models with subcommands `list`, `pull <name>`, `remove <name>`, and `select|set-default <name>`.
    - config: load and print configuration sections and values from an optional path.
    
    Performs terminal restoration where applicable and prints or exits on fatal runtime errors.
    """
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None or args.command == "run":
        host = getattr(args, "host", "localhost")
        port = getattr(args, "port", 7878)
        no_status_indicator = getattr(args, "no_status_indicator", False)
        _run_combined(host, port, status_indicator=not no_status_indicator)
        return

    if args.command == "bridge":
        _run_bridge(args.host, args.port)
        return

    if args.command == "tui":
        try:
            tui_process = _run_tui(args.host, args.port)
            tui_process.wait()
        except KeyboardInterrupt:
            pass
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)
        finally:
            _restore_terminal_state()
        return

    if args.command == "models":
        from whisper_local.model_manager import (
            download_model,
            list_installed_models,
            remove_model,
            set_selected_model,
        )

        if args.models_command == "list":
            for model in list_installed_models():
                variants = getattr(model, "variants", None)
                if isinstance(variants, dict):
                    fw_variant = variants.get("faster-whisper")
                    cpp_variant = variants.get("whisper.cpp")
                    fw_state = "installed" if fw_variant and fw_variant.installed else "available"
                    wcpp_state = "installed" if cpp_variant and cpp_variant.installed else "available"
                    print(f"{model.name}: faster-whisper={fw_state}, whisper.cpp={wcpp_state}")
                else:
                    state = "installed" if bool(getattr(model, "installed", False)) else "available"
                    print(f"{model.name}: {state}")
            return
        if args.models_command == "pull":
            if args.runtime == "faster-whisper":
                download_model(args.name)
                print(f"Downloaded {args.name}")
            else:
                download_model(args.name, runtime=args.runtime)
                print(f"Downloaded {args.name} ({args.runtime})")
            return
        if args.models_command == "remove":
            if args.runtime == "faster-whisper":
                remove_model(args.name)
                print(f"Removed {args.name}")
            else:
                remove_model(args.name, runtime=args.runtime)
                print(f"Removed {args.name} ({args.runtime})")
            return
        if args.models_command in ("select", "set-default"):
            set_selected_model(args.name)
            print(f"Selected model set to {args.name}")
            return

    if args.command == "config":
        config = load_config(args.path)
        for section, values in config.to_dict().items():
            if not isinstance(values, dict):
                print(f"{section} = {values}")
                continue
            print(f"[{section}]")
            for key, value in values.items():
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        print(f"{key}.{sub_key} = {sub_value}")
                else:
                    print(f"{key} = {value}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()