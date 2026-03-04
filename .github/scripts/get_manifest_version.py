#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: get_manifest_version.py <manifest-path>", file=sys.stderr)
        return 1

    manifest_path = Path(sys.argv[1])
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        print(payload["version"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"Error: unable to read version from {manifest_path}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: failed to parse {manifest_path}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
