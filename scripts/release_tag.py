#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

TAG_PATTERN = re.compile(
    r"^v(?P<core>\d+\.\d+\.\d+)"
    r"(?:(?P<pre>(?:a|b|rc)\d+)|(?P<post>\.post\d+)|(?P<dev>\.dev\d+))?$"
)


@dataclass(frozen=True)
class ReleaseTagInfo:
    tag: str
    version_no_v: str
    release_kind: str
    is_prerelease: bool


def classify_release_tag(tag: str) -> ReleaseTagInfo:
    value = tag.strip()
    match = TAG_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(
            "Invalid release tag. Expected canonical PEP 440 with v prefix, such as "
            "v1.2.3, v1.2.3.post1, v1.2.4rc1, v1.2.4a1, v1.2.4b2, or v1.2.4.dev1."
        )

    version_no_v = value[1:]
    if match.group("post"):
        release_kind = "post"
        is_prerelease = False
    elif match.group("pre") or match.group("dev"):
        release_kind = "prerelease"
        is_prerelease = True
    else:
        release_kind = "stable"
        is_prerelease = False

    return ReleaseTagInfo(
        tag=value,
        version_no_v=version_no_v,
        release_kind=release_kind,
        is_prerelease=is_prerelease,
    )


def write_github_outputs(path: Path, info: ReleaseTagInfo) -> None:
    lines = [
        f"normalized_tag={info.tag}",
        f"version_no_v={info.version_no_v}",
        f"release_kind={info.release_kind}",
        f"is_prerelease={'true' if info.is_prerelease else 'false'}",
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify release tag semantics.")
    parser.add_argument("tag", help="Git tag to classify (must include v prefix).")
    parser.add_argument(
        "--github-output",
        default="",
        help="Optional path to GITHUB_OUTPUT for writing workflow step outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        info = classify_release_tag(args.tag)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"tag={info.tag}")
    print(f"version_no_v={info.version_no_v}")
    print(f"release_kind={info.release_kind}")
    print(f"is_prerelease={str(info.is_prerelease).lower()}")
    if args.github_output:
        write_github_outputs(Path(args.github_output), info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
