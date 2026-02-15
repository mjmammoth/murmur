#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """
    Builds and parses command-line arguments for the version synchronization check.
    
    Defines two optional flags:
    - --pyproject: path to pyproject.toml (default: "pyproject.toml")
    - --init-file: path to the package __init__.py (default: "src/whisper_local/__init__.py")
    
    Returns:
        argparse.Namespace: Parsed arguments with attributes `pyproject` and `init_file`.
    """
    parser = argparse.ArgumentParser(description="Ensure package versions stay synchronized.")
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml",
    )
    parser.add_argument(
        "--init-file",
        default="src/whisper_local/__init__.py",
        help="Path to package __init__.py",
    )
    return parser.parse_args()


def read_pyproject_version(path: Path) -> str:
    """
    Read the package version declared in the pyproject.toml [project] table.
    
    Parameters:
        path (Path): Path to the pyproject.toml file to read.
    
    Returns:
        version (str): The value of `[project].version` as a string.
    
    Raises:
        ValueError: If the `[project].version` key is missing or empty in the given file.
    """
    with path.open("rb") as handle:
        parsed = tomllib.load(handle)
    project = parsed.get("project", {})
    version = project.get("version")
    if not version:
        raise ValueError(f"Unable to read [project].version from {path}")
    return str(version)


def read_init_version(path: Path) -> str:
    """
    Extract the package version string from the given __init__.py file.
    
    Parameters:
        path (Path): Path to the package __init__.py file to read.
    
    Returns:
        str: The version value assigned to `__version__`.
    
    Raises:
        ValueError: If no `__version__` assignment is found in the file.
    """
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if match is None:
        raise ValueError(f"Unable to find __version__ assignment in {path}")
    return match.group(1)


def main() -> int:
    """
    Check that the version in pyproject.toml matches the __version__ in the package __init__.py.
    
    Prints a success message to stdout when the versions match, or prints detailed mismatch information to stderr when they differ.
    
    Returns:
        int: 0 if the versions match, 1 if they differ.
    """
    args = parse_args()
    pyproject_path = Path(args.pyproject)
    init_path = Path(args.init_file)

    pyproject_version = read_pyproject_version(pyproject_path)
    init_version = read_init_version(init_path)

    if pyproject_version != init_version:
        print(
            "Version mismatch detected:\n"
            f"- {pyproject_path}: {pyproject_version}\n"
            f"- {init_path}: {init_version}",
            file=sys.stderr,
        )
        return 1

    print(f"Version sync OK: {pyproject_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())