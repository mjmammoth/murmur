#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageFilter

THEMES = ["dark", "catppuccin-mocha", "light"]
CAPTURE_GEOMETRY = "120x32"
DEFAULT_CAPTURE_SECONDS = 4.0
DEFAULT_SNAPSHOT_DELAY = 2.6
README_START = "<!-- tui-showcase:start -->"
README_END = "<!-- tui-showcase:end -->"
RENDERER_AUTO = "auto"
RENDERER_TERMTOSVG = "termtosvg"
RENDERER_GHOSTTY = "ghostty"
DEFAULT_FONT_FAMILY = (
    "'JetBrainsMono Nerd Font Mono', 'JetBrainsMono Nerd Font', "
    "'JetBrains Mono', 'DejaVu Sans Mono', monospace"
)
DEFAULT_FONT_SIZE_PX = 14

TRANSCRIPT_LINES = [
    "Create a modern and clean diagram from the below description.",
    "In GCP, I am trying to get an App Engine deployment of my static docs hosted with a custom domain.",
    "Check the objective infrastructure repo; I am trying to build to Cloud Run and route traffic safely.",
]


def _clear_capture_target(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def _resolve_svg_capture(path: Path) -> Path:
    if path.is_file():
        return path

    if path.is_dir():
        candidates = [candidate for candidate in path.rglob("*.svg") if candidate.is_file()]
        if candidates:
            candidates.sort(key=lambda candidate: candidate.name)
            # Prefer the earliest frame with maximal transcript coverage and
            # item count. This avoids selecting teardown tail frames.
            transcript_markers = [line[:48].strip() for line in TRANSCRIPT_LINES]
            best_candidate: Path | None = None
            best_score: tuple[int, int] | None = None
            best_index = 10**9
            for index, candidate in enumerate(candidates):
                text = candidate.read_text(encoding="utf-8", errors="ignore")
                if "Ready" not in text or "large-v3-turbo" not in text:
                    continue
                transcript_matches = sum(1 for marker in transcript_markers if marker and marker in text)
                items_match = re.search(r"(\d+)\s+items?", text)
                item_count = int(items_match.group(1)) if items_match else 0
                score = (transcript_matches, item_count)
                if (
                    best_score is None
                    or score > best_score
                    or (score == best_score and index < best_index)
                ):
                    best_candidate = candidate
                    best_score = score
                    best_index = index
            if best_candidate is not None:
                return best_candidate
            # Fallback to latest frame if no fully-populated snapshot was found.
            return candidates[-1]

    raise FileNotFoundError(
        f"Could not find rendered SVG at '{path}'. "
        "termtosvg may have failed before producing output."
    )


def _sanitize_termtosvg_svg(path: Path) -> None:
    svg_text = path.read_text(encoding="utf-8", errors="ignore")
    cleaned = re.sub(r'\s*text-decoration="underline"', "", svg_text)
    if cleaned != svg_text:
        path.write_text(cleaned, encoding="utf-8")


def _sanitize_termtosvg_capture(path: Path) -> None:
    if path.is_dir():
        for candidate in path.rglob("*.svg"):
            if candidate.is_file():
                _sanitize_termtosvg_svg(candidate)
        return
    if path.is_file() and path.suffix.lower() == ".svg":
        _sanitize_termtosvg_svg(path)


def _pick_port() -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
    except PermissionError:
        # Some restricted environments disallow local binds during port probing.
        return random.randint(20000, 59999)


def _resolve_renderer(renderer: str) -> str:
    if renderer != RENDERER_AUTO:
        return renderer
    if sys.platform == "darwin" and os.environ.get("TERM_PROGRAM", "").lower() == "ghostty":
        return RENDERER_GHOSTTY
    return RENDERER_TERMTOSVG


def _start_mock_backend(repo_root: Path, theme: str, port: int) -> subprocess.Popen[str]:
    bun_path = shutil.which("bun")
    if not bun_path:
        raise RuntimeError("Could not find 'bun' on PATH. Install Bun and ensure it is in PATH.")

    server_cmd = [
        bun_path,
        "run",
        "tui/scripts/mock-demo-backend.ts",
        "--port",
        str(port),
        "--theme",
        theme,
    ]
    server = subprocess.Popen(
        server_cmd,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(0.5)
    if server.poll() is not None:
        output = server.stdout.read() if server.stdout else ""
        raise RuntimeError(
            f"Mock backend exited before startup (code={server.returncode}).\n{output}"
        )
    return server


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if not process:
        return
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _set_terminal_title(title: str) -> None:
    if not sys.stdout.isatty():
        return
    # OSC 0 sets the terminal window title in common terminal emulators.
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def _front_ghostty_window_id(
    *,
    title_token: str | None = None,
    max_attempts: int = 12,
    retry_delay: float = 0.15,
) -> int:
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListOptionOnScreenOnly,
        )
    except Exception as exc:
        raise RuntimeError(
            "Ghostty renderer requires pyobjc Quartz bindings. "
            "Install with: python3 -m pip install pyobjc-framework-Quartz"
        ) from exc

    for _ in range(max_attempts):
        windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []
        fallback_window_id: int | None = None
        for window in windows:
            owner_name = str(window.get("kCGWindowOwnerName", "")).lower()
            layer = int(window.get("kCGWindowLayer", 1))
            if owner_name != "ghostty" or layer != 0:
                continue
            window_id = window.get("kCGWindowNumber")
            if window_id is None:
                continue
            window_id = int(window_id)
            if fallback_window_id is None:
                fallback_window_id = window_id
            if title_token:
                name = str(window.get("kCGWindowName", ""))
                if title_token in name:
                    return window_id
            else:
                return window_id
        if title_token and fallback_window_id is not None:
            # Keep polling briefly for the title propagation.
            time.sleep(retry_delay)
            continue
        if fallback_window_id is not None:
            return fallback_window_id
        time.sleep(retry_delay)

    if title_token:
        raise RuntimeError(
            "Could not find the Ghostty window for this capture session. "
            "Run the command from the Ghostty window you want to capture."
        )
    raise RuntimeError(
        "Could not find an on-screen Ghostty window. "
        "Keep a Ghostty window visible and focused while generating screenshots."
    )


def _looks_blank_capture(svg_path: Path) -> bool:
    svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
    return svg_text.count("<text") < 10


def run_capture_termtosvg(
    repo_root: Path,
    theme: str,
    port: int,
    svg_path: Path,
    capture_seconds: float,
) -> Path:
    bun_path = shutil.which("bun")
    if not bun_path:
        raise RuntimeError("Could not find 'bun' on PATH. Install Bun and ensure it is in PATH.")
    termtosvg_runner = repo_root / "scripts" / "termtosvg_compat.py"
    if not termtosvg_runner.exists():
        raise RuntimeError(f"Missing termtosvg compat runner: {termtosvg_runner}")

    tui_cmd = f"{bun_path} run src/index.tsx -- --host 127.0.0.1 --port {port}"

    termtosvg_cmd = [
        sys.executable,
        str(termtosvg_runner),
        "--still",
        "--screen-geometry",
        CAPTURE_GEOMETRY,
        "-c",
        tui_cmd,
        str(svg_path),
    ]

    _clear_capture_target(svg_path)
    capture_env = os.environ.copy()
    capture_env["WHISPER_LOCAL_TUI_CAPTURE_SECONDS"] = f"{capture_seconds:.2f}"
    server = _start_mock_backend(repo_root=repo_root, theme=theme, port=port)
    try:
        stdin_read_fd, stdin_write_fd = os.pipe()
        termtosvg_process = None
        try:
            with os.fdopen(stdin_read_fd, "rb", closefd=True) as stdin_read:
                termtosvg_process = subprocess.Popen(
                    termtosvg_cmd,
                    cwd=repo_root / "tui",
                    env=capture_env,
                    stdin=stdin_read,
                )
                return_code = termtosvg_process.wait()
            if return_code != 0:
                raise RuntimeError(
                    f"termtosvg failed with exit code {return_code}"
                )
        finally:
            os.close(stdin_write_fd)
            if termtosvg_process and termtosvg_process.poll() is None:
                termtosvg_process.terminate()
                try:
                    termtosvg_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    termtosvg_process.kill()
                    termtosvg_process.wait(timeout=5)
    finally:
        _stop_process(server)
    _sanitize_termtosvg_capture(svg_path)
    rendered_svg = _resolve_svg_capture(svg_path)
    svg_text = rendered_svg.read_text(encoding="utf-8", errors="ignore")
    if "Cannot find module 'react/jsx-dev-runtime'" in svg_text:
        raise RuntimeError(
            "TUI capture failed: Bun resolved JSX to react runtime. "
            "Ensure capture runs from the 'tui' directory with the TUI tsconfig."
        )
    if _looks_blank_capture(rendered_svg):
        raise RuntimeError(
            "Blank capture frame detected (only cursor/empty terminal). "
            "This usually means termtosvg exited too early."
        )
    return rendered_svg


def run_capture_ghostty(
    repo_root: Path,
    theme: str,
    port: int,
    png_path: Path,
    capture_seconds: float,
    snapshot_delay: float,
) -> None:
    bun_path = shutil.which("bun")
    if not bun_path:
        raise RuntimeError("Could not find 'bun' on PATH. Install Bun and ensure it is in PATH.")

    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    in_tmux = bool(os.environ.get("TMUX"))
    if term_program != "ghostty" and not in_tmux:
        raise RuntimeError(
            "Ghostty renderer requires running this command from Ghostty "
            "(or tmux inside Ghostty)."
        )

    title_token = f"whisper-local-capture-{os.getpid()}-{theme}"
    _set_terminal_title(title_token)
    # Give the terminal a moment to apply the title before querying windows.
    time.sleep(0.1)
    window_id = _front_ghostty_window_id(title_token=None if in_tmux else title_token)
    capture_env = os.environ.copy()
    capture_env["WHISPER_LOCAL_TUI_CAPTURE_SECONDS"] = f"{capture_seconds:.2f}"
    tui_cmd = [
        bun_path,
        "run",
        "src/index.tsx",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    screenshot_cmd = [
        "sh",
        "-c",
        f"sleep {snapshot_delay:.2f}; screencapture -x -o -l {window_id} '{png_path}'",
    ]

    _clear_capture_target(png_path)
    server = _start_mock_backend(repo_root=repo_root, theme=theme, port=port)
    screenshot_proc: subprocess.Popen[str] | None = None
    try:
        screenshot_proc = subprocess.Popen(screenshot_cmd, cwd=repo_root, env=capture_env)
        completed = subprocess.run(
            tui_cmd,
            cwd=repo_root / "tui",
            env=capture_env,
            check=False,
        )
        # Capture mode exits with SIGKILL by design so the terminal reset sequence
        # does not overwrite the frame being screenshotted.
        if completed.returncode not in (0, -9):
            raise RuntimeError(
                f"TUI process failed during Ghostty capture (exit={completed.returncode})"
            )
        if screenshot_proc.wait(timeout=max(6.0, capture_seconds + 2.0)) != 0:
            raise RuntimeError("Failed to capture Ghostty window screenshot.")
    finally:
        _stop_process(screenshot_proc)
        _stop_process(server)

    if not png_path.exists():
        raise RuntimeError(f"Ghostty screenshot not created: {png_path}")


def svg_to_png(
    svg_path: Path,
    png_path: Path,
    font_family: str,
    font_size_px: int,
    preserve_text_length: bool,
) -> None:
    import cairosvg

    svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
    svg_text = re.sub(
        r"font-family:\s*'[^']*',\s*monospace;",
        f"font-family: {font_family};",
        svg_text,
    )
    svg_text = re.sub(
        r"font-size:\s*\d+(?:\.\d+)?px;",
        f"font-size: {font_size_px}px;",
        svg_text,
    )
    if not preserve_text_length:
        # textLength can force awkward inter-character spacing when font metrics
        # differ from termtosvg's default assumptions.
        svg_text = re.sub(r'\stextLength="[^"]+"', "", svg_text)
    cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), write_to=str(png_path))


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


def _svg_dimensions(svg_text: str) -> tuple[int, int]:
    root = ET.fromstring(svg_text)
    view_box = root.attrib.get("viewBox", "")
    if view_box:
        parts = view_box.replace(",", " ").split()
        if len(parts) == 4:
            try:
                width = int(float(parts[2]))
                height = int(float(parts[3]))
                if width > 0 and height > 0:
                    return width, height
            except ValueError:
                pass

    width_attr = root.attrib.get("width", "960")
    height_attr = root.attrib.get("height", "546")
    width_match = re.match(r"(\d+(?:\.\d+)?)", width_attr)
    height_match = re.match(r"(\d+(?:\.\d+)?)", height_attr)
    width = int(float(width_match.group(1))) if width_match else 960
    height = int(float(height_match.group(1))) if height_match else 546
    return max(width, 1), max(height, 1)


def compose_stacked_svg(theme_svgs: list[tuple[str, Path]], output_path: Path) -> None:
    theme_to_svg = {theme: path for theme, path in theme_svgs}
    ordered_themes = [theme for theme in THEMES if theme in theme_to_svg and theme != "dark"]
    if "dark" in theme_to_svg:
        ordered_themes.append("dark")
    for theme in theme_to_svg:
        if theme not in ordered_themes:
            ordered_themes.append(theme)

    ordered_paths = [theme_to_svg[theme] for theme in ordered_themes]
    svg_texts = [path.read_text(encoding="utf-8", errors="ignore") for path in ordered_paths]
    dimensions = [_svg_dimensions(text) for text in svg_texts]

    target_width = min(width for width, _ in dimensions)
    x_step = 56
    y_step = 40

    scaled_sizes: list[tuple[int, int]] = []
    for width, height in dimensions:
        if width == target_width:
            scaled_sizes.append((width, height))
            continue
        scaled_height = int(height * (target_width / width))
        scaled_sizes.append((target_width, max(scaled_height, 1)))

    max_w = max(width for width, _ in scaled_sizes)
    max_h = max(height for _, height in scaled_sizes)
    canvas_w = max_w + x_step * (len(scaled_sizes) - 1) + 80
    canvas_h = max_h + y_step * (len(scaled_sizes) - 1) + 80

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {canvas_w} {canvas_h}">',
    ]
    for i, (svg_text, (width, height)) in enumerate(zip(svg_texts, scaled_sizes)):
        x = 30 + i * x_step
        y = 24 + i * y_step
        encoded = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
        lines.append(
            f'<image x="{x}" y="{y}" width="{width}" height="{height}" '
            f'href="data:image/svg+xml;base64,{encoded}"/>'
        )
    lines.append("</svg>")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        default="docs/assets",
        help="Directory for generated image assets",
    )
    parser.add_argument("--readme", default="README.md", help="README path")
    parser.add_argument(
        "--renderer",
        choices=[RENDERER_AUTO, RENDERER_GHOSTTY, RENDERER_TERMTOSVG],
        default=os.environ.get("WHISPER_LOCAL_SHOWCASE_RENDERER", RENDERER_AUTO),
        help="Capture renderer: auto, ghostty (real window screenshot), or termtosvg",
    )
    parser.add_argument(
        "--capture-seconds",
        default=float(os.environ.get("WHISPER_LOCAL_SHOWCASE_CAPTURE_SECONDS", str(DEFAULT_CAPTURE_SECONDS))),
        type=float,
        help="Seconds to keep TUI alive during each capture",
    )
    parser.add_argument(
        "--snapshot-delay",
        default=float(os.environ.get("WHISPER_LOCAL_SHOWCASE_SNAPSHOT_DELAY", str(DEFAULT_SNAPSHOT_DELAY))),
        type=float,
        help="Delay before taking Ghostty window screenshot",
    )
    parser.add_argument(
        "--font-family",
        default=os.environ.get("WHISPER_LOCAL_SHOWCASE_FONT_FAMILY", DEFAULT_FONT_FAMILY),
        help="CSS font-family used when rasterizing captured SVGs",
    )
    parser.add_argument(
        "--font-size",
        default=os.environ.get("WHISPER_LOCAL_SHOWCASE_FONT_SIZE", str(DEFAULT_FONT_SIZE_PX)),
        type=int,
        help="Font size in px used when rasterizing captured SVGs",
    )
    parser.add_argument(
        "--preserve-text-length",
        action="store_true",
        help="Keep termtosvg textLength attributes (default removes them for cleaner spacing)",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    assets_dir = (repo_root / args.assets_dir).resolve()
    readme_path = (repo_root / args.readme).resolve()
    renderer = _resolve_renderer(args.renderer)

    assets_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale in-repo per-theme captures from previous versions.
    for theme in THEMES:
        _clear_capture_target(assets_dir / f"home-{theme}.svg")
        _clear_capture_target(assets_dir / f"home-{theme}.png")

    final_svg = assets_dir / "tui-home-themes.svg"
    final_png = assets_dir / "tui-home-themes.png"

    with tempfile.TemporaryDirectory(prefix="whisper-local-showcase-") as temp_dir:
        capture_dir = Path(temp_dir)
        theme_pngs: list[Path] = []
        theme_svgs: list[tuple[str, Path]] = []
        for theme in THEMES:
            svg_path = capture_dir / f"home-{theme}.svg"
            png_path = capture_dir / f"home-{theme}.png"
            attempts = 0
            capture_seconds = max(1.0, args.capture_seconds)
            snapshot_delay = max(0.8, min(args.snapshot_delay, max(1.2, capture_seconds - 0.6)))
            while True:
                attempts += 1
                try:
                    if renderer == RENDERER_GHOSTTY:
                        _clear_capture_target(svg_path)
                        run_capture_ghostty(
                            repo_root=repo_root,
                            theme=theme,
                            port=_pick_port(),
                            png_path=png_path,
                            capture_seconds=capture_seconds,
                            snapshot_delay=snapshot_delay,
                        )
                        theme_pngs.append(png_path)
                    else:
                        _clear_capture_target(png_path)
                        rendered_svg = run_capture_termtosvg(
                            repo_root=repo_root,
                            theme=theme,
                            port=_pick_port(),
                            svg_path=svg_path,
                            capture_seconds=capture_seconds,
                        )
                        theme_svgs.append((theme, rendered_svg))
                    break
                except RuntimeError as exc:
                    message = str(exc)
                    if attempts >= 8:
                        raise
                    if (
                        "EADDRINUSE" in message
                        or "Blank capture frame detected" in message
                        or "Failed to capture Ghostty window screenshot" in message
                    ):
                        capture_seconds = min(capture_seconds + 1.0, 10.0)
                        snapshot_delay = min(snapshot_delay + 0.5, max(1.2, capture_seconds - 0.3))
                        continue
                    raise

        if renderer == RENDERER_TERMTOSVG and theme_svgs:
            _clear_capture_target(final_png)
            stacked = final_svg
            compose_stacked_svg(theme_svgs, stacked)
        else:
            _clear_capture_target(final_svg)
            stacked = final_png
            compose_stacked_image(theme_pngs, stacked)

    update_readme(readme_path, stacked.relative_to(repo_root))

    print("Generated:")
    print(f"- {stacked.relative_to(repo_root)}")
    print(f"Updated README: {readme_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
