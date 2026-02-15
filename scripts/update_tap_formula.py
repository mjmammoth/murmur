#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from string import Template


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for rendering the Homebrew formula for whisper-local.
    
    Returns:
        argparse.Namespace: Parsed arguments with attributes:
            - version: release version (no "v" prefix)
            - wheel_url: URL to the Python wheel
            - wheel_sha256: SHA256 hash for the Python wheel
            - tui_url: URL to the TUI tarball
            - tui_sha256: SHA256 hash for the TUI tarball
            - repository: GitHub repository in "owner/name" format
            - tap_repo_path: path to the local Homebrew tap repository checkout
            - formula_path: formula path relative to the tap repository
            - template: path to the formula template file
    """
    parser = argparse.ArgumentParser(description="Render Homebrew formula for whisper-local.")
    parser.add_argument("--version", required=True, help="Release version without v prefix")
    parser.add_argument("--wheel-url", required=True, help="URL to Python wheel")
    parser.add_argument("--wheel-sha256", required=True, help="SHA256 for Python wheel")
    parser.add_argument("--tui-url", required=True, help="URL to TUI tarball")
    parser.add_argument("--tui-sha256", required=True, help="SHA256 for TUI tarball")
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="GitHub repository in owner/name format",
    )
    parser.add_argument(
        "--tap-repo-path",
        required=True,
        help="Path to local homebrew tap repo checkout",
    )
    parser.add_argument(
        "--formula-path",
        default="Formula/whisper-local.rb",
        help="Formula path relative to tap repo",
    )
    parser.add_argument(
        "--template",
        default=str(Path(__file__).resolve().parent / "templates" / "whisper-local.rb.tpl"),
        help="Path to formula template",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """
    Validate release-related command-line arguments and raise ValueError for any invalid value.
    
    Parameters:
        args (argparse.Namespace): Namespace expected to contain:
            - version: semantic version string (no leading "v")
            - repository: GitHub repository in the form "owner/name"
            - wheel_url: URL to a Python wheel (must end with ".whl")
            - wheel_sha256: 64-hex-character SHA256 of the wheel
            - tui_url: URL to a TUI tarball (must end with ".tar.gz")
            - tui_sha256: 64-hex-character SHA256 of the TUI tarball
    
    Raises:
        ValueError: If any of the following conditions occur:
            - `version` does not match the expected version pattern
            - `repository` is empty or does not contain a slash
            - `wheel_url` does not end with ".whl"
            - `tui_url` does not end with ".tar.gz"
            - `wheel_sha256` or `tui_sha256` is not a 64-character hexadecimal string
    """
    if not VERSION_PATTERN.match(args.version):
        raise ValueError(f"Invalid version: {args.version}")
    if not args.repository or "/" not in args.repository:
        raise ValueError(f"Invalid repository value: {args.repository!r}")
    if not args.wheel_url.endswith(".whl"):
        raise ValueError(f"Expected wheel URL ending in .whl: {args.wheel_url}")
    if not args.tui_url.endswith(".tar.gz"):
        raise ValueError(f"Expected TUI URL ending in .tar.gz: {args.tui_url}")
    for label, value in (
        ("wheel-sha256", args.wheel_sha256),
        ("tui-sha256", args.tui_sha256),
    ):
        if not re.fullmatch(r"[A-Fa-f0-9]{64}", value):
            raise ValueError(f"Invalid {label}: {value}")


def render_formula(args: argparse.Namespace) -> str:
    """
    Render the Homebrew formula template using values from the parsed arguments.
    
    Parameters:
        args (argparse.Namespace): Parsed arguments that must include the following attributes:
            - template: path to the template file
            - version: release version string
            - repository: GitHub repository identifier (owner/repo)
            - wheel_url: URL to the Python wheel
            - wheel_sha256: SHA256 hex digest for the wheel
            - tui_url: URL to the TUI tarball
            - tui_sha256: SHA256 hex digest for the TUI tarball
    
    Returns:
        str: The rendered Homebrew formula content with template placeholders substituted.
    """
    template_path = Path(args.template)
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.substitute(
        VERSION=args.version,
        REPOSITORY=args.repository,
        WHEEL_URL=args.wheel_url,
        WHEEL_SHA256=args.wheel_sha256,
        TUI_URL=args.tui_url,
        TUI_SHA256=args.tui_sha256,
    )


def write_formula(rendered_formula: str, tap_repo_path: Path, formula_path: Path) -> Path:
    """
    Write the rendered Homebrew formula into the tap repository at the specified path.
    
    Parameters:
        rendered_formula (str): The formula content to write.
        tap_repo_path (Path): Filesystem path to the root of the Homebrew tap repository.
        formula_path (Path): Path to the formula file relative to `tap_repo_path`.
    
    Returns:
        Path: The full path to the written formula file.
    """
    output_path = tap_repo_path / formula_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered_formula, encoding="utf-8")
    return output_path


def main() -> int:
    """
    Parse command-line arguments, validate them, render the Homebrew formula from the template, and write the rendered formula into the specified tap repository.
    
    Returns:
        exit_code (int): 0 on success.
    
    Raises:
        FileNotFoundError: If the resolved tap repository path does not exist.
    """
    args = parse_args()
    validate_args(args)

    tap_repo_path = Path(args.tap_repo_path).resolve()
    if not tap_repo_path.exists():
        raise FileNotFoundError(f"Tap repo path does not exist: {tap_repo_path}")

    rendered_formula = render_formula(args)
    output_path = write_formula(
        rendered_formula=rendered_formula,
        tap_repo_path=tap_repo_path,
        formula_path=Path(args.formula_path),
    )
    print(f"Updated formula: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)