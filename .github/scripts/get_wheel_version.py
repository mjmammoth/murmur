#!/usr/bin/env python3
from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: get_wheel_version.py <wheel-path>", file=sys.stderr)
        return 1

    wheel_path = Path(sys.argv[1])
    try:
        with zipfile.ZipFile(wheel_path) as whl:
            metadata_path = next(
                (m for m in whl.namelist() if m.endswith(".dist-info/METADATA")),
                None,
            )
            if metadata_path is None:
                print(f"Error: no .dist-info/METADATA found in {wheel_path}", file=sys.stderr)
                return 1

            version_line = next(
                (
                    line
                    for line in whl.read(metadata_path).decode("utf-8").splitlines()
                    if line.startswith("Version: ")
                ),
                None,
            )
            if version_line is None:
                print(f"Error: no Version field in {metadata_path}", file=sys.stderr)
                return 1

            print(version_line.split(": ", 1)[1].strip())
    except (FileNotFoundError, zipfile.BadZipFile) as exc:
        print(f"Error: unable to read wheel {wheel_path}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
