from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from whisper_local.config import load_config
from whisper_local.model_manager import (
    download_model,
    list_installed_models,
    remove_model,
    set_selected_model,
)
from whisper_local.transcribe import ensure_whisper_cpp_installed


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=(Path(sys.argv[0]).name or "whisper.local"))
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the TUI (bridge + TypeScript frontend)")
    run_parser.add_argument("--host", default="localhost", help="Bridge host")
    run_parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    run_parser.add_argument("--legacy", action="store_true", help="Use legacy Textual TUI")
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

    remove_parser = models_sub.add_parser("remove", help="Remove a model")
    remove_parser.add_argument("name")

    select_parser = models_sub.add_parser(
        "select",
        aliases=["set-default"],
        help="Select model",
    )
    select_parser.add_argument("name")

    config_parser = subparsers.add_parser("config", help="Show config")
    config_parser.add_argument("--path", type=Path)

    return parser


def _get_tui_path() -> Path:
    """Get path to the tui directory."""
    # First check relative to the package
    pkg_dir = Path(__file__).parent.parent.parent.parent
    tui_path = pkg_dir / "tui"
    if tui_path.exists():
        return tui_path
    # Fallback to cwd
    cwd_tui = Path.cwd() / "tui"
    if cwd_tui.exists():
        return cwd_tui
    raise FileNotFoundError("Cannot find tui directory. Make sure you're in the project root.")


def _check_bun() -> bool:
    """Check if bun is installed."""
    return shutil.which("bun") is not None


def _ensure_runtime_dependencies() -> None:
    """Fail fast with actionable message when required runtime deps are missing."""
    try:
        ensure_whisper_cpp_installed()
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)


def _run_bridge(host: str, port: int, capture_logs: bool = False) -> None:
    """Run the bridge server."""
    _ensure_runtime_dependencies()
    from whisper_local.bridge import run_bridge
    config = load_config()
    run_bridge(config, host, port, capture_logs=capture_logs)


def _run_tui(host: str, port: int) -> subprocess.Popen:
    """Start the TypeScript TUI."""
    tui_path = _get_tui_path()
    # Run from tui directory so bunfig.toml is picked up for the OpenTUI plugin
    cmd = ["bun", "src/index.tsx", "--host", host, "--port", str(port)]
    return subprocess.Popen(cmd, cwd=str(tui_path))


def _start_status_indicator(host: str, port: int) -> subprocess.Popen | None:
    """Start the macOS menu bar status indicator sidecar."""
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
    """Run both bridge and TUI together."""
    _ensure_runtime_dependencies()
    if not _check_bun():
        print("Error: bun is not installed. Install it with: curl -fsSL https://bun.sh/install | bash")
        sys.exit(1)

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
        print("Make sure you're running from the project root directory.", file=real_stderr)
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
            loop = bridge_server._loop
            if loop and not loop.is_closed():
                loop.call_soon_threadsafe(loop.stop)
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
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None or args.command == "run":
        host = getattr(args, "host", "localhost")
        port = getattr(args, "port", 7878)
        legacy = getattr(args, "legacy", False)
        no_status_indicator = getattr(args, "no_status_indicator", False)
        _ensure_runtime_dependencies()

        if legacy:
            # Use legacy Textual TUI
            from whisper_local.tui import run_app
            run_app()
        else:
            # Use new TypeScript TUI
            _run_combined(host, port, status_indicator=not no_status_indicator)
        return

    if args.command == "bridge":
        _run_bridge(args.host, args.port)
        return

    if args.command == "tui":
        if not _check_bun():
            print("Error: bun is not installed. Install it with: curl -fsSL https://bun.sh/install | bash")
            sys.exit(1)
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
        if args.models_command == "list":
            for model in list_installed_models():
                state = "installed" if model.installed else "available"
                print(f"{model.name}: {state}")
            return
        if args.models_command == "pull":
            download_model(args.name)
            print(f"Downloaded {args.name}")
            return
        if args.models_command == "remove":
            remove_model(args.name)
            print(f"Removed {args.name}")
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
