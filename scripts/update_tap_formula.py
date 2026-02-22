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
    Parse command-line arguments for rendering and writing a Homebrew formula for whisper-local.
    
    The returned namespace contains the following attributes: version, wheel_url, wheel_sha256, tui_url, tui_sha256, repository, tap_repo_path, formula_path, and template. The `--repository` value defaults to the GITHUB_REPOSITORY environment variable when present.
     
    Returns:
        args (argparse.Namespace): Parsed command-line arguments with attributes used to render and write the formula.
    """
    parser = argparse.ArgumentParser(description="Render Homebrew formula for whisper-local.")
    parser.add_argument("--version", default="", help="Release version without v prefix")
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
    Validate parsed CLI arguments for expected formats and required values.
    
    Checks that:
    - `args.version`, if provided, matches the module-level VERSION_PATTERN.
    - `args.repository` is non-empty and contains a forward slash.
    - `args.wheel_url` ends with ".whl".
    - `args.tui_url` ends with ".tar.gz".
    - `args.wheel_sha256` and `args.tui_sha256` are 64-character hexadecimal strings.
    
    Parameters:
        args (argparse.Namespace): Parsed command-line arguments produced by parse_args().
    
    Raises:
        ValueError: If any argument fails its validation check (invalid version, repository,
        wheel/tui URL suffix, or SHA256 format).
    """
    if args.version and not VERSION_PATTERN.match(args.version):
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
    Render a Homebrew formula by substituting placeholders in a template with values from `args`.
    
    Parameters:
        args (argparse.Namespace): Parsed arguments providing values used for substitution:
            - repository: value for `REPOSITORY`
            - wheel_url: value for `WHEEL_URL`
            - wheel_sha256: value for `WHEEL_SHA256`
            - tui_url: value for `TUI_URL`
            - tui_sha256: value for `TUI_SHA256`
            - template: filesystem path to the template file
    
    Returns:
        str: Rendered formula content with all placeholders substituted.
    """
    template_path = Path(args.template)
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.substitute(
        REPOSITORY=args.repository,
        WHEEL_URL=args.wheel_url,
        WHEEL_SHA256=args.wheel_sha256,
        TUI_URL=args.tui_url,
        TUI_SHA256=args.tui_sha256,
    )


def write_formula(rendered_formula: str, tap_repo_path: Path, formula_path: Path) -> Path:
    """
    Write the rendered Homebrew formula into the tap repository and return the written file path.
    
    Parameters:
        rendered_formula (str): The templated formula content to write.
        tap_repo_path (Path): Filesystem path to the root of the tap repository.
        formula_path (Path): Path to the formula file relative to `tap_repo_path`.
    
    Returns:
        output_path (Path): The full path to the written formula file inside the tap repository.
    """
    output_path = tap_repo_path / formula_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered_formula, encoding="utf-8")
    return output_path


def main() -> int:
    """
    Run the script workflow: parse and validate arguments, render the Homebrew formula from the template, and write it into the specified tap repository.
    
    Raises:
        FileNotFoundError: If the resolved tap repository path does not exist.
    
    Returns:
        int: Exit code 0 on success.
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