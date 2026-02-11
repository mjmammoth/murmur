from __future__ import annotations

import argparse
import logging
from pathlib import Path

from whisper_local.config import load_config
from whisper_local.model_manager import (
    download_model,
    list_installed_models,
    remove_model,
    set_default_model,
)
from whisper_local.tui import run_app


logging.basicConfig(level=logging.INFO)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whisper-local")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="Start the TUI")

    models_parser = subparsers.add_parser("models", help="Manage models")
    models_sub = models_parser.add_subparsers(dest="models_command")
    models_sub.add_parser("list", help="List available models")

    pull_parser = models_sub.add_parser("pull", help="Download a model")
    pull_parser.add_argument("name")

    remove_parser = models_sub.add_parser("remove", help="Remove a model")
    remove_parser.add_argument("name")

    default_parser = models_sub.add_parser("set-default", help="Set default model")
    default_parser.add_argument("name")

    config_parser = subparsers.add_parser("config", help="Show config")
    config_parser.add_argument("--path", type=Path)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in (None, "run"):
        run_app()
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
        if args.models_command == "set-default":
            set_default_model(args.name)
            print(f"Default model set to {args.name}")
            return

    if args.command == "config":
        config = load_config(args.path)
        for section, values in config.to_dict().items():
            print(f"[{section}]")
            for key, value in values.items():
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        print(f"{key}.{sub_key} = {sub_value}")
                else:
                    print(f"{key} = {value}")
        return

    parser.print_help()
