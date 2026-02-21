#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageFilter
import cairosvg

THEMES = ["dark", "catppuccin-mocha", "light"]
CAPTURE_GEOMETRY = "120x32"
CAPTURE_SECONDS = "2.4"
README_START = "<!-- tui-showcase:start -->"
README_END = "<!-- tui-showcase:end -->"

TRANSCRIPT_LINES = [
    "Create a modern and clean diagram from the below description.",
    "In GCP, I am trying to get an App Engine deployment of my static docs hosted with a custom domain.",
    "Check the objective infrastructure repo; I am trying to build to Cloud Run and route traffic safely.",
]


def run_capture(repo_root: Path, theme: str, port: int, svg_path: Path) -> None:
    server_cmd = [
        "bun",
        "run",
        "tui/scripts/mock-demo-backend.ts",
        "--port",
        str(port),
        "--theme",
        theme,
    ]

    tui_cmd = (
        f"env WHISPER_LOCAL_TUI_CAPTURE_SECONDS={CAPTURE_SECONDS} "
        f"bun run tui/src/index.tsx -- --host 127.0.0.1 --port {port}"
    )

    termtosvg_cmd = [
        "termtosvg",
        "--still",
        "--screen-geometry",
        CAPTURE_GEOMETRY,
        "-c",
        tui_cmd,
        str(svg_path),
    ]

    server = subprocess.Popen(server_cmd, cwd=repo_root)
    try:
        time.sleep(0.8)
        subprocess.run(termtosvg_cmd, cwd=repo_root, check=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def svg_to_png(svg_path: Path, png_path: Path) -> None:
    cairosvg.svg2png(url=str(svg_path), write_to=str(png_path))


def compose_stacked_image(png_paths: list[Path], output_path: Path) -> None:
    cards = [Image.open(path).convert("RGBA") for path in png_paths]
    try:
        resized = []
        target_width = min(card.width for card in cards)
        for card in cards:
            if card.width == target_width:
                resized.append(card)
                continue
            target_height = int(card.height * (target_width / card.width))
            resized.append(card.resize((target_width, target_height), Image.Resampling.LANCZOS))

        x_step = 56
        y_step = 40
        shadow_blur = 12
        border = 2

        max_w = max(img.width for img in resized)
        max_h = max(img.height for img in resized)
        canvas_w = max_w + x_step * (len(resized) - 1) + 80
        canvas_h = max_h + y_step * (len(resized) - 1) + 80

        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

        for i, card in enumerate(resized):
            x = 30 + i * x_step
            y = 24 + i * y_step

            framed = Image.new("RGBA", (card.width + border * 2, card.height + border * 2), (16, 16, 16, 255))
            framed.paste(card, (border, border))

            shadow = Image.new("RGBA", framed.size, (0, 0, 0, 150)).filter(ImageFilter.GaussianBlur(shadow_blur))
            canvas.alpha_composite(shadow, dest=(x + 8, y + 10))
            canvas.alpha_composite(framed, dest=(x, y))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path)
    finally:
        for card in cards:
            card.close()


def update_readme(readme_path: Path, image_path: Path) -> None:
    rel_image = image_path.as_posix()
    block = (
        f"{README_START}\n"
        f"![whisper.local TUI home across themes]({rel_image})\n\n"
        "Demo transcriptions shown:\n"
        f"- `{TRANSCRIPT_LINES[0]}`\n"
        f"- `{TRANSCRIPT_LINES[1]}`\n"
        f"- `{TRANSCRIPT_LINES[2]}`\n"
        f"{README_END}"
    )

    content = readme_path.read_text(encoding="utf-8")
    if README_START in content and README_END in content:
        start = content.index(README_START)
        end = content.index(README_END) + len(README_END)
        updated = content[:start] + block + content[end:]
    else:
        anchor = "## Install (pip)"
        insert_at = content.find(anchor)
        showcase_heading = "## TUI Showcase\n\n"
        if insert_at == -1:
            updated = content.rstrip() + "\n\n" + showcase_heading + block + "\n"
        else:
            updated = content[:insert_at] + showcase_heading + block + "\n\n" + content[insert_at:]

    if updated != content:
        readme_path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate TUI showcase images and update README.")
    parser.add_argument("--repo-root", default=".", help="Repository root path")
    parser.add_argument(
        "--assets-dir",
        default="docs/readme-assets/tui",
        help="Directory for generated image assets",
    )
    parser.add_argument("--readme", default="README.md", help="README path")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    assets_dir = (repo_root / args.assets_dir).resolve()
    readme_path = (repo_root / args.readme).resolve()

    assets_dir.mkdir(parents=True, exist_ok=True)

    theme_pngs: list[Path] = []
    for index, theme in enumerate(THEMES):
        svg_path = assets_dir / f"home-{theme}.svg"
        png_path = assets_dir / f"home-{theme}.png"
        run_capture(repo_root, theme, 8787 + index, svg_path)
        svg_to_png(svg_path, png_path)
        theme_pngs.append(png_path)

    stacked = assets_dir / "tui-home-themes.png"
    compose_stacked_image(theme_pngs, stacked)
    update_readme(readme_path, stacked.relative_to(repo_root))

    print("Generated:")
    for path in [*theme_pngs, stacked]:
        print(f"- {path.relative_to(repo_root)}")
    print(f"Updated README: {readme_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
