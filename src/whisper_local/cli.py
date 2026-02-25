from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

from whisper_local.config import SUPPORTED_RUNTIMES, load_config
from whisper_local.platform import create_status_indicator_provider
from whisper_local.service_manager import ServiceManager
from whisper_local.tui_runtime import resolve_tui_runtime


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=(Path(sys.argv[0]).name or "whisper.local"))
    subparsers = parser.add_subparsers(dest="command")

    # Deprecated alias: preserve for compatibility, but behavior now matches `tui`.
    run_parser = subparsers.add_parser("run", help="[Deprecated] Attach TUI to service")
    run_parser.add_argument("--host", default="localhost", help="Bridge host")
    run_parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    run_parser.add_argument(
        "--no-status-indicator",
        action="store_true",
        help="Disable macOS menu bar status indicator while auto-starting service",
    )

    bridge_parser = subparsers.add_parser("bridge", help="Start only the WebSocket bridge server")
    bridge_parser.add_argument("--host", default="localhost", help="Bridge host")
    bridge_parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    bridge_parser.add_argument("--capture-logs", action="store_true", help=argparse.SUPPRESS)

    tui_parser = subparsers.add_parser(
        "tui",
        help="Attach the TypeScript TUI to the service (auto-starts service if needed)",
    )
    tui_parser.add_argument("--host", default="localhost", help="Bridge host")
    tui_parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    tui_parser.add_argument(
        "--no-status-indicator",
        action="store_true",
        help="Disable macOS menu bar status indicator while auto-starting service",
    )

    service_parser = subparsers.add_parser("service", help="Manage whisper.local background service")
    service_sub = service_parser.add_subparsers(dest="service_command")

    service_run = service_sub.add_parser("run", help="Start service")
    service_run.add_argument("--host", default="localhost", help="Bridge host")
    service_run.add_argument("--port", type=int, default=7878, help="Bridge port")
    service_run.add_argument(
        "--foreground",
        action="store_true",
        help="Run service in foreground (blocks current terminal)",
    )
    service_run.add_argument(
        "--no-status-indicator",
        action="store_true",
        help="Disable macOS menu bar status indicator",
    )

    service_sub.add_parser("stop", help="Stop service")
    service_sub.add_parser("status", help="Show service status")

    trigger_parser = subparsers.add_parser(
        "trigger",
        help="Control recording without opening TUI",
    )
    trigger_parser.add_argument("action", choices=("start", "stop", "toggle"))
    trigger_parser.add_argument("--host", default="localhost", help="Bridge host")
    trigger_parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    trigger_parser.add_argument(
        "--no-status-indicator",
        action="store_true",
        help="Disable macOS menu bar status indicator while auto-starting service",
    )

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

    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Upgrade whisper.local (auto-upgrade only for installer-managed installs)",
    )
    upgrade_parser.add_argument(
        "--version",
        help="Upgrade to a specific release tag (example: v0.2.0). Defaults to latest.",
    )

    return parser


def _run_bridge(host: str, port: int, capture_logs: bool = False) -> None:
    from whisper_local.bridge import run_bridge

    config = load_config()
    run_bridge(config, host, port, capture_logs=capture_logs)


def _run_tui(host: str, port: int) -> subprocess.Popen:
    runtime = resolve_tui_runtime(cli_file=__file__)
    logger.info("Starting TUI runtime mode=%s", runtime.mode)
    cmd = [*runtime.command, "--host", host, "--port", str(port)]
    return subprocess.Popen(cmd, cwd=str(runtime.cwd) if runtime.cwd else None)


def _restore_terminal_state() -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return

    try:
        sys.stdout.write("\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l\x1b[?25h\x1b[0m")
        sys.stdout.flush()
    except Exception:
        pass

    try:
        subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass


def _ensure_service_running(host: str, port: int, *, status_indicator: bool) -> None:
    manager = ServiceManager()
    manager.ensure_running(host=host, port=port, status_indicator=status_indicator)


def _run_tui_attach(host: str, port: int, *, status_indicator: bool) -> None:
    try:
        _ensure_service_running(host, port, status_indicator=status_indicator)
    except Exception as exc:
        print(f"Error: failed to start service: {exc}")
        raise SystemExit(1)

    try:
        tui_process = _run_tui(host, port)
        tui_process.wait()
    except KeyboardInterrupt:
        pass
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
    finally:
        _restore_terminal_state()


def _service_run(host: str, port: int, *, foreground: bool, status_indicator: bool) -> None:
    if foreground:
        indicator_provider = create_status_indicator_provider(host=host, port=port)
        if status_indicator:
            try:
                indicator_provider.start()
            except Exception:
                logger.warning("Failed to start status indicator", exc_info=True)
        try:
            _run_bridge(host, port, capture_logs=True)
        finally:
            try:
                indicator_provider.stop()
            except Exception:
                pass
        return

    manager = ServiceManager()
    status = manager.start_background(host=host, port=port, status_indicator=status_indicator)
    if status.running:
        print(f"Service running pid={status.pid} host={status.host} port={status.port}")
    elif status.stale:
        print("Service state was stale and has been cleaned up")
    else:
        print("Service start requested")


def _service_stop() -> None:
    manager = ServiceManager()
    before = manager.load_state()
    manager.stop()
    if before is None:
        print("Service is not running")
    else:
        print("Service stopped")


def _service_status() -> None:
    manager = ServiceManager()
    status = manager.status()
    if status.running:
        indicator = (
            f" indicator_pid={status.status_indicator_pid}"
            if status.status_indicator_pid is not None
            else ""
        )
        print(f"running pid={status.pid} host={status.host} port={status.port}{indicator}")
        return
    if status.stale:
        print(f"stale (cleaned) previous_pid={status.pid} host={status.host} port={status.port}")
        return
    print("stopped")


async def _trigger_async(host: str, port: int, action: str) -> None:
    import websockets

    uri = f"ws://{host}:{port}"
    async with websockets.connect(uri, ping_interval=10, ping_timeout=10) as websocket:
        current_status = ""
        for _ in range(4):
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=0.75)
            except TimeoutError:
                break
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "status":
                current_status = str(payload.get("status", ""))
                break

        effective = action
        if action == "toggle":
            effective = "stop" if current_status == "recording" else "start"

        message_type = "start_recording" if effective == "start" else "stop_recording"
        await websocket.send(json.dumps({"type": message_type}))


def _trigger(host: str, port: int, *, action: str, status_indicator: bool) -> None:
    try:
        _ensure_service_running(host, port, status_indicator=status_indicator)
    except Exception as exc:
        print(f"Error: failed to start service: {exc}")
        raise SystemExit(1)

    try:
        asyncio.run(_trigger_async(host, port, action))
    except Exception as exc:
        print(f"Error: trigger command failed: {exc}")
        raise SystemExit(1)


def _upgrade(*, requested_version: str | None) -> None:
    from whisper_local.upgrade import UpgradeActionRequired, UpgradeError, run_upgrade

    try:
        result = run_upgrade(requested_version=requested_version)
    except UpgradeActionRequired as exc:
        print(str(exc))
        raise SystemExit(2)
    except UpgradeError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)

    print(
        f"Upgraded whisper.local {result.previous_version} -> {result.new_version} "
        f"({result.tag})"
    )
    if result.restarted_service:
        print("Service was running and has been restarted.")


def _handle_models_command(args: argparse.Namespace) -> None:
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


def _handle_config_command(args: argparse.Namespace) -> None:
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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        _service_run("localhost", 7878, foreground=False, status_indicator=True)
        return

    if args.command == "run":
        print("Warning: 'run' is deprecated; use 'tui' instead.", file=sys.stderr)
        _run_tui_attach(
            args.host,
            args.port,
            status_indicator=not args.no_status_indicator,
        )
        return

    if args.command == "service":
        if args.service_command in {None, "run"}:
            _service_run(
                getattr(args, "host", "localhost"),
                getattr(args, "port", 7878),
                foreground=bool(getattr(args, "foreground", False)),
                status_indicator=not bool(getattr(args, "no_status_indicator", False)),
            )
            return
        if args.service_command == "stop":
            _service_stop()
            return
        if args.service_command == "status":
            _service_status()
            return

    if args.command == "bridge":
        _run_bridge(args.host, args.port, capture_logs=bool(getattr(args, "capture_logs", False)))
        return

    if args.command == "tui":
        _run_tui_attach(args.host, args.port, status_indicator=not args.no_status_indicator)
        return

    if args.command == "trigger":
        _trigger(
            args.host,
            args.port,
            action=args.action,
            status_indicator=not args.no_status_indicator,
        )
        return

    if args.command == "models":
        _handle_models_command(args)
        return

    if args.command == "config":
        _handle_config_command(args)
        return

    if args.command == "upgrade":
        _upgrade(requested_version=getattr(args, "version", None))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
