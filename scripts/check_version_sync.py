#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """
    Parse command-line options for locating pyproject.toml and the package __init__.py.
    
    Returns:
        argparse.Namespace: Parsed arguments with attributes:
            pyproject (str): Path to pyproject.toml (default: "pyproject.toml")
            init_file (str): Path to the package __init__.py (default: "src/whisper_local/__init__.py")
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
    Read the package version from a pyproject.toml file's [project].version field.
    
    Parameters:
        path (Path): Path to the pyproject.toml file to read.
    
    Returns:
        str: The value of `[project].version` as a string.
    
    Raises:
        ValueError: If `[project].version` is missing or empty in the file.
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
    Retrieve the package version declared in the given __init__.py file.
    
    Parameters:
        path (Path): Path to the __init__.py file to read. The file is expected to contain an assignment of the form `__version__ = "x.y.z"` or `__version__ = 'x.y.z'`.
    
    Returns:
        version (str): The string value assigned to `__version__` (without surrounding quotes).
    
    Raises:
        ValueError: If no `__version__` assignment in the expected format is found in the file.
    """
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^\s*__version__\s*=\s*(['\"])([^'\"]+)\1\s*$", text, re.MULTILINE)
    if match is None:
        raise ValueError(f"Unable to find __version__ assignment in {path}")
    return match.group(2)


def main() -> int:
    """
    Check that pyproject.toml and the package __init__.py contain the same version string.
    
    Reads the version from the pyproject file and from the package __init__ file, prints a success message to stdout when they match or a detailed mismatch message to stderr when they differ, and returns an appropriate exit status.
    
    Returns:
        int: 0 if the versions are identical, 1 if they differ.
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
