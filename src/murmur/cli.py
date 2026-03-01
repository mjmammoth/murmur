from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING, TypeAlias

from murmur import __version__
from murmur.config import SUPPORTED_RUNTIMES, load_config
from murmur.platform import create_status_indicator_provider
from murmur.service_manager import ServiceManager
from murmur.tui_runtime import resolve_tui_runtime

if TYPE_CHECKING:
    from murmur.service_state import ServiceStatus
    from websockets.asyncio.client import ClientConnection
    from websockets.legacy.client import WebSocketClientProtocol

    WebSocketClientType: TypeAlias = ClientConnection | WebSocketClientProtocol
else:
    WebSocketClientType = Any


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NO_STATUS_INDICATOR_AUTOSTART_HELP = (
    "Disable macOS menu bar status indicator while auto-starting service"
)
STATUS_SNAPSHOT_TIMEOUT_SECONDS = 1.5
FIRST_RUN_SETUP_MESSAGE = "First run setup required. Download and select a model in Model Manager."
SETUP_GUIDANCE_MODEL = "small"
RUNNING_LOOP_STATUS_MESSAGE = (
    "Runtime snapshot unavailable while an event loop is active; run murmur status from a synchronous shell."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=(Path(sys.argv[0]).name or "murmur"))
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Deprecated alias: preserve for compatibility, but behavior now matches `tui`.
    run_parser = subparsers.add_parser("run", help="[Deprecated] Attach TUI to service")
    run_parser.add_argument("--host", default="localhost", help="Bridge host")
    run_parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    run_parser.add_argument(
        "--no-status-indicator",
        action="store_true",
        help=NO_STATUS_INDICATOR_AUTOSTART_HELP,
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
        help=NO_STATUS_INDICATOR_AUTOSTART_HELP,
    )

    start_parser = subparsers.add_parser("start", help="Start service")
    start_parser.add_argument("--host", default="localhost", help="Bridge host")
    start_parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    start_parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run service in foreground (blocks current terminal)",
    )
    start_parser.add_argument(
        "--no-status-indicator",
        action="store_true",
        help="Disable macOS menu bar status indicator",
    )

    subparsers.add_parser("stop", help="Stop service")
    subparsers.add_parser("status", help="Show service status")

    trigger_parser = subparsers.add_parser(
        "trigger",
        help="Control recording without opening TUI",
    )
    trigger_parser.add_argument("action", choices=("start", "stop", "toggle"))
    trigger_parser.add_argument("--host", default="localhost", help="Bridge host")
    trigger_parser.add_argument("--port", type=int, default=7878, help="Bridge port")
    trigger_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=3.0,
        help="Max time to wait for trigger status acknowledgement",
    )
    trigger_parser.add_argument(
        "--no-status-indicator",
        action="store_true",
        help=NO_STATUS_INDICATOR_AUTOSTART_HELP,
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
        help="Upgrade murmur (auto-upgrade only for installer-managed installs)",
    )
    upgrade_parser.add_argument(
        "--version",
        help="Upgrade to a specific release tag (example: v0.2.0). Defaults to latest.",
    )

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Uninstall murmur (auto-uninstall only for installer-managed installs)",
    )
    uninstall_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts",
    )
    uninstall_parser.add_argument(
        "--remove-state",
        action="store_true",
        help="Remove ~/.local/state/murmur during uninstall",
    )
    uninstall_parser.add_argument(
        "--remove-config",
        action="store_true",
        help="Remove ~/.config/murmur during uninstall",
    )
    uninstall_parser.add_argument(
        "--remove-model-cache",
        action="store_true",
        help="Remove murmur model caches under ~/.cache/huggingface",
    )
    uninstall_parser.add_argument(
        "--all-data",
        action="store_true",
        help="Equivalent to --remove-state --remove-config --remove-model-cache",
    )

    subparsers.add_parser("version", help="Print installed murmur version")

    return parser


def _run_bridge(host: str, port: int, capture_logs: bool = False) -> None:
    from murmur.bridge import run_bridge

    config = load_config()
    run_bridge(config, host, port, capture_logs=capture_logs)


def _run_tui(host: str, port: int) -> subprocess.Popen[bytes]:
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


def _ensure_service_running(host: str, port: int, *, status_indicator: bool) -> ServiceStatus:
    manager = ServiceManager()
    return manager.ensure_running(host=host, port=port, status_indicator=status_indicator)


def _run_tui_attach(host: str, port: int, *, status_indicator: bool) -> None:
    try:
        service_status = _ensure_service_running(host, port, status_indicator=status_indicator)
    except Exception as exc:
        print(f"Error: failed to start service: {exc}")
        raise SystemExit(1)

    resolved_host = service_status.host or host
    resolved_port = service_status.port if service_status.port is not None else port

    try:
        tui_process = _run_tui(resolved_host, resolved_port)
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
        indicator_provider = None
        indicator_started = False
        if status_indicator:
            indicator_provider = create_status_indicator_provider(host=host, port=port)
            try:
                indicator_provider.start()
                indicator_started = True
            except Exception:
                logger.warning("Failed to start status indicator", exc_info=True)
        try:
            _run_bridge(host, port, capture_logs=True)
        finally:
            if indicator_provider is not None and indicator_started:
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
        host = status.host or "localhost"
        port = status.port if status.port is not None else 7878
        try:
            loop_running = False
            try:
                asyncio.get_running_loop()
                loop_running = True
            except RuntimeError:
                pass
            if loop_running:
                raise RuntimeError(RUNNING_LOOP_STATUS_MESSAGE)
            snapshot = asyncio.run(
                _runtime_status_snapshot(
                    host,
                    port,
                    kickoff_onboarding=True,
                    timeout_seconds=STATUS_SNAPSHOT_TIMEOUT_SECONDS,
                )
            )
            _print_runtime_status_snapshot(snapshot)
        except Exception as exc:
            error_message = f"Unable to query runtime state: {exc}"
            print(f"app_status=unknown message={json.dumps(error_message, ensure_ascii=True)}")
        return
    if status.stale:
        print(f"stale (cleaned) previous_pid={status.pid} host={status.host} port={status.port}")
        return
    print("stopped")


async def _wait_for_status(
    websocket: WebSocketClientType,
    *,
    timeout_seconds: float,
    expected_statuses: set[str] | None = None,
) -> tuple[str | None, str | None]:
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    last_status: str | None = None
    last_message: str | None = None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last_status, last_message
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        except TimeoutError:
            return last_status, last_message

        status_update = _extract_status_update(raw)
        if status_update is None:
            continue

        last_status, last_message = status_update
        if expected_statuses is None or last_status in expected_statuses:
            return last_status, last_message


def _extract_status_update(raw: str | bytes) -> tuple[str | None, str | None] | None:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "status":
        return None

    status = str(payload.get("status", ""))
    last_status = status or None
    status_message = payload.get("message")
    last_message = status_message if isinstance(status_message, str) else None
    return last_status, last_message


def _extract_config_update(raw: str | bytes) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "config":
        return None
    config = payload.get("config")
    if not isinstance(config, dict):
        return None
    return config


async def _collect_runtime_snapshot(
    websocket: WebSocketClientType,
    *,
    timeout_seconds: float,
    initial_status: str | None = None,
    initial_message: str | None = None,
    initial_config: dict[str, Any] | None = None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    status = initial_status
    message = initial_message
    config = initial_config

    while True:
        if status is not None and config is not None:
            return status, message, config
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return status, message, config
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        except TimeoutError:
            return status, message, config

        status_update = _extract_status_update(raw)
        if status_update is not None:
            status, message = status_update
            continue

        config_update = _extract_config_update(raw)
        if config_update is not None:
            config = config_update
            continue


def _startup_phase_from_config(config: dict[str, Any] | None) -> str:
    if not isinstance(config, dict):
        return ""
    startup = config.get("startup")
    if not isinstance(startup, dict):
        return ""
    value = startup.get("phase")
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _first_run_pending(config: dict[str, Any] | None) -> bool:
    if not isinstance(config, dict):
        return False
    return bool(config.get("first_run_setup_required"))


async def _runtime_status_snapshot(
    host: str,
    port: int,
    *,
    kickoff_onboarding: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    import websockets

    uri = f"ws://{host}:{port}?client=passive"
    async with websockets.connect(uri, ping_interval=10, ping_timeout=10) as websocket:
        snapshot_started = time.monotonic()
        status, message, config = await _collect_runtime_snapshot(
            websocket,
            timeout_seconds=timeout_seconds,
        )

        kickoff_sent = False
        if kickoff_onboarding and _first_run_pending(config):
            phase = _startup_phase_from_config(config)
            if phase in {"", "idle"}:
                await websocket.send(json.dumps({"type": "begin_onboarding_setup"}))
                kickoff_sent = True
                remaining_timeout = max(0.0, timeout_seconds - (time.monotonic() - snapshot_started))
                if remaining_timeout > 0:
                    status, message, config = await _collect_runtime_snapshot(
                        websocket,
                        timeout_seconds=remaining_timeout,
                        initial_status=status,
                        initial_message=message,
                        initial_config=config,
                    )

        return {
            "status": status,
            "message": message,
            "config": config,
            "kickoff_sent": kickoff_sent,
        }


def _print_runtime_status_snapshot(snapshot: dict[str, Any]) -> None:
    status = snapshot.get("status")
    message = snapshot.get("message")
    config = snapshot.get("config")
    kickoff_sent = bool(snapshot.get("kickoff_sent"))

    status_text = status if isinstance(status, str) and status else "unknown"
    message_text = message if isinstance(message, str) and message else "unknown"
    print(f"app_status={status_text} message={json.dumps(message_text, ensure_ascii=True)}")

    if not isinstance(config, dict):
        print("runtime_detail=unavailable")
        return

    first_run = _first_run_pending(config)
    startup = config.get("startup")
    startup_dict = startup if isinstance(startup, dict) else {}
    phase = _startup_phase_from_config(config) or "unknown"
    blockers = startup_dict.get("blockers")
    blocker_list = [str(item) for item in blockers] if isinstance(blockers, list) else []
    close_ready = bool(startup_dict.get("onboarding_close_ready"))

    if not first_run and status_text == "ready" and close_ready and not blocker_list:
        print("app_ready=true")
        return

    runtime_probe = str(startup_dict.get("runtime_probe", "unknown"))
    audio_scan = str(startup_dict.get("audio_scan", "unknown"))
    components = str(startup_dict.get("components", "unknown"))
    model_state = str(startup_dict.get("model", "unknown"))
    print(
        "startup "
        f"phase={phase} runtime_probe={runtime_probe} "
        f"audio_scan={audio_scan} components={components} model={model_state}"
    )

    if blocker_list:
        print("startup_blockers:")
        for blocker in blocker_list:
            print(f"  - {blocker}")

    if first_run:
        if kickoff_sent:
            print("setup_init=started_via_status")
        print(f"setup_required=true message={json.dumps(FIRST_RUN_SETUP_MESSAGE, ensure_ascii=True)}")
        print("next_steps:")
        print(f"  murmur models pull {SETUP_GUIDANCE_MODEL}")
        print(f"  murmur models select {SETUP_GUIDANCE_MODEL}")
        print("  murmur status")


async def _trigger_async(host: str, port: int, action: str, timeout_seconds: float) -> str:
    import websockets

    uri = f"ws://{host}:{port}"
    async with websockets.connect(uri, ping_interval=10, ping_timeout=10) as websocket:
        initial_status, _ = await _wait_for_status(
            websocket,
            timeout_seconds=min(max(timeout_seconds, 0.1), 0.75),
        )
        current_status = initial_status or ""

        effective = action
        if action == "toggle":
            effective = "stop" if current_status == "recording" else "start"

        if effective == "start":
            expected_statuses = {"recording", "connecting", "error"}
            should_return_without_send = current_status == "recording"
        else:
            expected_statuses = {"transcribing", "ready", "error"}
            should_return_without_send = current_status in {"transcribing", "ready"}

        if should_return_without_send:
            return current_status

        message_type = "start_recording" if effective == "start" else "stop_recording"
        await websocket.send(json.dumps({"type": message_type}))

        ack_status, ack_message = await _wait_for_status(
            websocket,
            timeout_seconds=timeout_seconds,
            expected_statuses=expected_statuses,
        )
        if ack_status in expected_statuses:
            return str(ack_status)

        last_status = ack_status or current_status or "unknown"
        last_message = ack_message or "no status message"
        raise TimeoutError(
            f"Timed out waiting for trigger acknowledgement ({effective}); "
            f"last_status={last_status}; last_message={last_message}"
        )


def _trigger(
    host: str,
    port: int,
    *,
    action: str,
    status_indicator: bool,
    timeout_seconds: float,
) -> None:
    try:
        service_status = _ensure_service_running(host, port, status_indicator=status_indicator)
    except Exception as exc:
        print(f"Error: failed to start service: {exc}")
        raise SystemExit(1)

    resolved_host = service_status.host or host
    resolved_port = service_status.port if service_status.port is not None else port

    try:
        ack_status = asyncio.run(_trigger_async(resolved_host, resolved_port, action, timeout_seconds))
        print(f"Trigger acknowledged: status={ack_status}")
    except TimeoutError as exc:
        print(f"Error: trigger command timed out: {exc}")
        raise SystemExit(2)
    except Exception as exc:
        print(f"Error: trigger command failed: {exc}")
        raise SystemExit(1)


def _upgrade(*, requested_version: str | None) -> None:
    from murmur.upgrade import UpgradeActionRequired, UpgradeError, run_upgrade

    try:
        result = run_upgrade(requested_version=requested_version)
    except UpgradeActionRequired as exc:
        print(str(exc))
        raise SystemExit(2)
    except UpgradeError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)

    print(
        f"Upgraded murmur {result.previous_version} -> {result.new_version} "
        f"({result.tag})"
    )
    if result.restarted_service:
        print("Service was running and has been restarted.")


def _resolve_uninstall_scope(args: argparse.Namespace) -> tuple[bool, bool, bool, bool]:
    remove_state = bool(getattr(args, "remove_state", False))
    remove_config = bool(getattr(args, "remove_config", False))
    remove_model_cache = bool(getattr(args, "remove_model_cache", False))
    if bool(getattr(args, "all_data", False)):
        remove_state = True
        remove_config = True
        remove_model_cache = True
    explicit_scope = any([remove_state, remove_config, remove_model_cache, bool(getattr(args, "all_data", False))])
    return remove_state, remove_config, remove_model_cache, explicit_scope


def _prompt_uninstall_scope() -> tuple[bool, bool, bool]:
    print("Select uninstall scope:")
    print("  1) App/runtime only")
    print("  2) App/runtime + local state/config")
    print("  3) App/runtime + local state/config + model cache")
    while True:
        choice = input("Choice [1-3] (default: 1): ").strip() or "1"
        if choice == "1":
            return False, False, False
        if choice == "2":
            return True, True, False
        if choice == "3":
            return True, True, True
        print("Invalid choice. Enter 1, 2, or 3.")


def _print_uninstall_plan(*, remove_state: bool, remove_config: bool, remove_model_cache: bool) -> None:
    print("Uninstall plan:")
    print("  - Remove installer launchers and runtime under ~/.local/share/murmur")
    if remove_state:
        print("  - Remove ~/.local/state/murmur")
    if remove_config:
        print("  - Remove ~/.config/murmur")
    if remove_model_cache:
        print("  - Remove murmur model caches under ~/.cache/huggingface/hub")


def _confirm_uninstall() -> bool:
    response = input("Proceed with uninstall? [y/N]: ").strip().lower()
    return response in {"y", "yes"}


def _uninstall(args: argparse.Namespace) -> None:
    from murmur.uninstall import (
        UninstallActionRequired,
        UninstallError,
        UninstallOptions,
        run_uninstall,
    )

    remove_state, remove_config, remove_model_cache, explicit_scope = _resolve_uninstall_scope(args)
    tty_session = sys.stdin.isatty() and sys.stdout.isatty()
    assume_yes = bool(getattr(args, "yes", False))

    if not assume_yes and not tty_session and not explicit_scope:
        print(
            "Error: non-interactive uninstall requires --yes or explicit scope flags "
            "(--remove-state/--remove-config/--remove-model-cache/--all-data).",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if tty_session and not assume_yes:
        if not explicit_scope:
            remove_state, remove_config, remove_model_cache = _prompt_uninstall_scope()
        _print_uninstall_plan(
            remove_state=remove_state,
            remove_config=remove_config,
            remove_model_cache=remove_model_cache,
        )
        if not _confirm_uninstall():
            print("Uninstall cancelled.")
            raise SystemExit(1)

    options = UninstallOptions(
        remove_state=remove_state,
        remove_config=remove_config,
        remove_model_cache=remove_model_cache,
    )

    try:
        result = run_uninstall(options=options)
    except UninstallActionRequired as exc:
        print(str(exc))
        raise SystemExit(2)
    except UninstallError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)

    if result.removed_paths:
        print("Removed paths:")
        for path in result.removed_paths:
            print(f"  - {path}")
    else:
        print("No files were removed.")

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")

    if result.failed_paths:
        print("Failed to remove:")
        for failure in result.failed_paths:
            print(f"  - {failure.path}: {failure.reason}")
        raise SystemExit(1)

    print("Uninstall complete.")


def _print_version() -> None:
    print(__version__)


def _handle_models_command(args: argparse.Namespace) -> None:
    from murmur.model_manager import (
        download_model,
        list_installed_models,
        remove_model,
        set_selected_model,
    )

    if args.models_command is None:
        print(
            "Error: No subcommand provided for 'models'. Use --help for options.",
            file=sys.stderr,
        )
        raise SystemExit(2)

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
        _service_status()
        print()
        parser.print_help()
        return

    if args.command == "run":
        print("Warning: 'run' is deprecated; use 'tui' instead.", file=sys.stderr)
        _run_tui_attach(
            args.host,
            args.port,
            status_indicator=not args.no_status_indicator,
        )
        return

    if args.command == "start":
        _service_run(
            args.host,
            args.port,
            foreground=args.foreground,
            status_indicator=not args.no_status_indicator,
        )
        return

    if args.command == "stop":
        _service_stop()
        return

    if args.command == "status":
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
            timeout_seconds=float(args.timeout_seconds),
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

    if args.command == "uninstall":
        _uninstall(args)
        return

    if args.command == "version":
        _print_version()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
