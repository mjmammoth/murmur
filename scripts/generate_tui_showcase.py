#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

THEMES = ["dark", "catppuccin-mocha", "light"]
THEME_CAPTURE_PORTS = {
    "dark": 18787,
    "catppuccin-mocha": 18788,
    "light": 18789,
}
# The mock backend emits exactly four demo transcript entries.
MIN_TRANSCRIPT_ITEMS = 4
CAPTURE_GEOMETRY = "100x28"
DEFAULT_CAPTURE_SECONDS = 4.0
README_START = "<!-- tui-showcase:start -->"
README_END = "<!-- tui-showcase:end -->"
OUTPUT_SVG = "svg"
OUTPUT_PNG = "png"
DEFAULT_PNG_SCALE = 2.0
FONT_FAMILY = "'JetBrainsMono Nerd Font Mono', 'JetBrainsMono Nerd Font', 'JetBrains Mono', monospace"
FONT_TTF_URL = (
    "https://raw.githubusercontent.com/ryanoasis/nerd-fonts/"
    "ae57d27445e9d85db49fc917c5276c5d249109c8/"
    "patched-fonts/JetBrainsMono/Ligatures/Regular/JetBrainsMonoNerdFontMono-Regular.ttf"
)
FONT_TTF_SHA256 = "f01031f40e48dc29e1112e6b0b0450a2c6cd097f3f35cfff05c55cb311f8034c"


def _secure_temp_root(repo_root: Path) -> Path:
    temp_root = repo_root / ".tmp" / "showcase"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        temp_root.chmod(0o700)
    except OSError:
        # Windows may not support POSIX chmod semantics; best effort is enough here.
        pass
    return temp_root


def _clear_capture_target(path: Path) -> None:
    """
    Ensure the given filesystem path is removed if it exists.

    If `path` is a directory, remove it and its contents recursively; if it is a file or symlink, unlink it. Do nothing when the path does not exist.
    """
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def _resolve_svg_capture(path: Path) -> Path:
    """
    Resolve a path pointing to a rendered SVG file or a directory containing SVG frames and return the best SVG to use.

    Parameters:
        path (Path): A file path to an SVG or a directory containing termtosvg-generated SVG files.

    Returns:
        Path: The resolved SVG file to use. If `path` is a file, it is returned unchanged. If `path` is a directory, returns the preferred SVG frame (prefer frames that indicate readiness and contain a populated item count; otherwise the most recent SVG).

    Raises:
        FileNotFoundError: If `path` is neither an existing SVG file nor a directory containing any SVG files.
    """
    if path.is_file():
        return path

    if path.is_dir():
        candidates = [candidate for candidate in path.rglob("*.svg") if candidate.is_file()]
        if candidates:
            candidates.sort(key=lambda candidate: candidate.name)
            # Prefer frames with more transcript items and expected ready/model markers.
            best_candidate: Path | None = None
            best_score: tuple[int, int, int, int] | None = None
            best_index = 10**9
            for index, candidate in enumerate(candidates):
                text = candidate.read_text(encoding="utf-8", errors="ignore")
                item_count = _extract_transcript_item_count(text)
                score = (
                    item_count,
                    1 if "Ready" in text else 0,
                    1 if "large-v3-turbo" in text else 0,
                    1 if "Transcripts" in text else 0,
                )
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
            return candidates[-1]

    raise FileNotFoundError(
        f"Could not find rendered SVG at '{path}'. "
        "termtosvg may have failed before producing output."
    )


def _extract_transcript_item_count(text: str) -> int:
    """
    Extract the largest "<n> item(s)" count from text using a linear scan.
    """
    max_items = 0
    marker = " item"
    search_from = 0

    while True:
        marker_index = text.find(marker, search_from)
        if marker_index == -1:
            break

        end = marker_index - 1
        while end >= 0 and text[end].isspace():
            end -= 1

        start = end
        while start >= 0 and text[start].isdigit():
            start -= 1

        if start < end:
            count = int(text[start + 1 : end + 1])
            if count > max_items:
                max_items = count

        search_from = marker_index + len(marker)

    return max_items


def _sanitize_termtosvg_svg(path: Path) -> None:
    """
    Remove text-decoration="underline" attributes from an SVG file in-place.

    Reads the SVG at `path`, strips any occurrences of the `text-decoration="underline"` attribute, and overwrites the file only if changes were made.

    Parameters:
        path (Path): Path to the SVG file to sanitize.
    """
    svg_text = path.read_text(encoding="utf-8", errors="ignore")
    cleaned = re.sub(r'\s*text-decoration="underline"', "", svg_text)
    if cleaned != svg_text:
        path.write_text(cleaned, encoding="utf-8")


def _sanitize_termtosvg_capture(path: Path) -> None:
    """
    Apply termtosvg-specific sanitization to an SVG file or to all SVG files contained in a directory.

    Modifies matching files in place to remove or adjust attributes in termtosvg-generated SVGs that may cause rendering issues (for example, removing underline text decoration).
    """
    if path.is_dir():
        for candidate in path.rglob("*.svg"):
            if candidate.is_file():
                _sanitize_termtosvg_svg(candidate)
        return
    if path.is_file() and path.suffix.lower() == ".svg":
        _sanitize_termtosvg_svg(path)


def _is_port_available(port: int) -> bool:
    """
    Check whether a specific TCP port is available on localhost.

    Attempts to bind to 127.0.0.1 on the given port. Returns True if the
    bind succeeds (port is available), False otherwise. Any OSError during
    the bind (e.g. port in use, PermissionError) causes a False return.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def _pick_capture_port(theme: str) -> int:
    """
    Pick a deterministic available TCP port for a theme capture run.

    The function starts from a theme-specific preferred port and scans forward
    to find an available local port.

    Parameters:
        theme (str): Theme name being captured.

    Returns:
        int: An available local TCP port.

    Raises:
        RuntimeError: If no port is available in the probe range.
    """
    base_port = THEME_CAPTURE_PORTS.get(theme, 18790)
    for offset in range(100):
        candidate = base_port + offset
        if _is_port_available(candidate):
            return candidate
    raise RuntimeError(f"Could not find available capture port for theme '{theme}'.")


def _wait_for_server(port: int, timeout: float = 5.0, interval: float = 0.1) -> bool:
    """
    Poll the localhost HTTP endpoint on the given port until a server responds or the timeout elapses.

    This function considers any HTTP response (including HTTP errors) as confirmation that the server is up.

    Parameters:
        port (int): TCP port on 127.0.0.1 to poll.
        timeout (float): Maximum number of seconds to wait before giving up.
        interval (float): Seconds to wait between polling attempts.

    Returns:
        `true` if a response was received before the timeout elapsed, `false` otherwise.
    """
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=interval):
                return True
        except urllib.error.HTTPError:
            # Any HTTP response confirms the server is up.
            return True
        except (OSError, urllib.error.URLError):
            time.sleep(interval)
    return False


def _start_mock_backend(repo_root: Path, theme: str, port: int) -> subprocess.Popen[str]:
    """
    Start a mock demo backend process serving the specified theme on localhost at the given port.

    Returns:
        subprocess.Popen[str]: The started backend process.

    Raises:
        RuntimeError: If the `bun` executable is not found on PATH.
        RuntimeError: If the backend fails to start within the readiness timeout or exits prematurely.
    """
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
    if not _wait_for_server(port):
        if server.poll() is not None:
            output = server.stdout.read() if server.stdout else ""
            raise RuntimeError(
                f"Mock backend exited before startup (code={server.returncode}).\n{output}"
            )
        raise RuntimeError("Mock backend did not start in time")
    if server.poll() is not None:
        output = server.stdout.read() if server.stdout else ""
        raise RuntimeError(
            f"Mock backend exited before startup (code={server.returncode}).\n{output}"
        )
    return server


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    """
    Terminate a running subprocess if it is still active, waiting briefly for it to exit.

    Parameters:
        process (subprocess.Popen[str] | None): The subprocess to stop; ignored if `None` or already exited.

    Description:
        Sends SIGTERM to the process and waits up to 5 seconds for it to exit. If the process does not exit within that time, it is forcibly killed and a short final wait is performed. No exception is raised for a `None` or already-terminated process.
    """
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


def _looks_blank_capture(svg_path: Path) -> bool:
    """
    Detects whether an SVG capture appears blank.

    Considers a capture blank when the file contains fewer than 10 `<text>` elements.

    Parameters:
    	svg_path (Path): Path to the SVG file to inspect.

    Returns:
    	`true` if the SVG contains fewer than 10 `<text>` elements, `false` otherwise.
    """
    svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
    return svg_text.count("<text") < 10


def run_capture_termtosvg(
    repo_root: Path,
    theme: str,
    port: int,
    svg_path: Path,
    capture_seconds: float,
) -> Path:
    """
    Capture a TUI session for a given theme using a mock backend and produce a rendered SVG file.

    Parameters:
        repo_root (Path): Repository root directory containing the TUI and helper scripts.
        theme (str): Theme name to run in the mock backend (e.g., "dark", "light").
        port (int): TCP port for the mock backend to bind.
        svg_path (Path): Target file or directory path where the termtosvg output will be written.
        capture_seconds (float): Duration, in seconds, to record the TUI session.

    Returns:
        rendered_svg (Path): Path to the resolved, sanitized SVG file containing the captured frame.

    Raises:
        RuntimeError: If Bun is not found on PATH, the termtosvg compatibility runner is missing,
                      termtosvg exits with a non-zero code, the capture contains a JSX runtime resolution error,
                      or the resulting capture appears blank.
    """
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
    capture_env.setdefault("TZ", "UTC")
    capture_env.setdefault("LANG", "C.UTF-8")
    capture_env.setdefault("LC_ALL", "C.UTF-8")
    capture_env["MURMUR_TUI_CAPTURE_SECONDS"] = f"{capture_seconds:.2f}"
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
                wait_timeout = max(5.0, capture_seconds + 5.0)
                try:
                    return_code = termtosvg_process.wait(timeout=wait_timeout)
                except subprocess.TimeoutExpired as exc:
                    termtosvg_process.terminate()
                    try:
                        termtosvg_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        termtosvg_process.kill()
                        termtosvg_process.wait(timeout=5)
                    raise RuntimeError(
                        "termtosvg capture timed out "
                        f"(capture_seconds={capture_seconds:.2f}, timeout={wait_timeout:.2f})"
                    ) from exc
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
    item_count = _extract_transcript_item_count(svg_text)
    if item_count < MIN_TRANSCRIPT_ITEMS:
        raise RuntimeError(
            "Incomplete capture frame detected "
            f"(items={item_count}, expected>={MIN_TRANSCRIPT_ITEMS})."
        )
    return rendered_svg


def _svg_dimensions(svg_text: str) -> tuple[int, int]:
    """
    Determine the pixel width and height of an SVG document.

    Parses the SVG text and returns integer dimensions extracted from the `viewBox`
    if present and valid; otherwise falls back to the `width` and `height`
    attributes. If numeric values cannot be determined, returns default dimensions
    (960 by 546). Returned values are at least 1.

    Parameters:
        svg_text (str): The full SVG document as a string.

    Returns:
        tuple[int, int]: A (width, height) pair in pixels.
    """
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


def _extract_svg_canvas_color(svg_text: str) -> str:
    # Prefer the first painted row color in the rendered frame; this represents
    # the actual theme canvas color better than termtosvg's default `.background`.
    """
    Extract the primary canvas fill color from an SVG capture.

    Searches the SVG text for the first rectangle drawn at the top-left (origin) and returns its `fill` value, which represents the frame's canvas color. If no such rectangle is found, returns the default dark color "#0c0c0c".

    Parameters:
        svg_text (str): Full SVG document text to inspect.

    Returns:
        str: The canvas color as found in the SVG (e.g. "#282828"), or "#0c0c0c" if not detected.
    """
    match = re.search(
        r"<g>\s*<rect[^>]*\bx=\"0\"[^>]*\by=\"0\"[^>]*\bfill=\"([^\"]+)\"",
        svg_text,
    )
    if match:
        return match.group(1)
    return "#0c0c0c"


def _sha256_file(path: Path) -> str:
    """
    Return the SHA-256 hash of a file as a lowercase hexadecimal string.

    Parameters:
        path (Path): The file path to hash.

    Returns:
        str: The SHA-256 digest in hex form.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_font(dest: Path) -> Path:
    """
    Ensure the JetBrains Mono Nerd Font is present in the destination directory and return its file path.

    Parameters:
        dest (Path): Directory to store or locate the cached font file.

    Returns:
        Path: Path to the JetBrains Mono Nerd Font TTF file.

    Raises:
        RuntimeError: If downloading the font fails or the downloaded payload checksum does not match the pinned digest.
    """
    font_path = dest / "JetBrainsMonoNerdFontMono-Regular.ttf"
    dest.mkdir(parents=True, exist_ok=True)
    if font_path.exists():
        if _sha256_file(font_path) == FONT_TTF_SHA256:
            return font_path
        font_path.unlink()

    tmp_path = font_path.with_suffix(".ttf.download")
    try:
        with urllib.request.urlopen(FONT_TTF_URL, timeout=30) as response, tmp_path.open("wb") as out:
            shutil.copyfileobj(response, out)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Failed to download font from {FONT_TTF_URL} to {tmp_path}: {exc}"
        ) from exc
    downloaded_sha = _sha256_file(tmp_path)
    if downloaded_sha != FONT_TTF_SHA256:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Downloaded font checksum mismatch. "
            f"expected={FONT_TTF_SHA256} actual={downloaded_sha}"
        )
    tmp_path.replace(font_path)
    return font_path


def render_svg_to_png(svg_path: Path, png_path: Path, png_scale: float, repo_root: Path) -> None:
    """
    Render an SVG file to a PNG image using headless Chromium via Playwright.

    Renders svg_path into png_path at a given raster scale by loading the SVG into a temporary HTML page
    that embeds a bundled JetBrains Mono Nerd Font so Chromium can rasterize text consistently across environments.
    The function writes temporary helper files into repo_root during rendering and removes them on completion.

    Parameters:
        svg_path (Path): Path to the source SVG file to render.
        png_path (Path): Destination path for the generated PNG image; parent directories are created as needed.
        png_scale (float): Raster scale (device pixel ratio) to apply; values less than 1.0 are treated as 1.0.
        repo_root (Path): Repository root used to cache fonts and to place temporary render files.

    Raises:
        RuntimeError: If Node.js is not found on PATH, Playwright rendering fails (non-zero exit), or the PNG output is not produced.
    """
    scale = max(1.0, png_scale)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
    width, height = _svg_dimensions(svg_text)

    # Patch font-family in the SVG to use JetBrains Mono Nerd Font.
    svg_text = re.sub(
        r"font-family:\s*'[^']*',\s*monospace;",
        f"font-family: {FONT_FAMILY};",
        svg_text,
    )

    # Download font for environments where it's not system-installed (CI).
    font_cache = repo_root / ".font-cache"
    font_path = _download_font(font_cache)

    # Create an HTML wrapper with @font-face so Chromium loads the font
    # regardless of whether it's installed on the system.
    html_content = f"""\
<!DOCTYPE html>
<html>
<head>
<style>
@font-face {{
  font-family: 'JetBrainsMono Nerd Font Mono';
  src: url('file://{font_path.resolve().as_posix()}') format('truetype');
  font-weight: normal;
  font-style: normal;
}}
@font-face {{
  font-family: 'JetBrainsMono Nerd Font';
  src: url('file://{font_path.resolve().as_posix()}') format('truetype');
  font-weight: normal;
  font-style: normal;
}}
@font-face {{
  font-family: 'JetBrains Mono';
  src: url('file://{font_path.resolve().as_posix()}') format('truetype');
  font-weight: normal;
  font-style: normal;
}}
body {{ margin: 0; padding: 0; }}
</style>
</head>
<body>
{svg_text}
</body>
</html>
"""
    tmp_html = repo_root / f".tmp-playwright-render-{os.getpid()}.html"
    tmp_html.write_text(html_content, encoding="utf-8")

    html_url_json = json.dumps(f"file://{tmp_html.resolve().as_posix()}")
    png_path_json = json.dumps(png_path.resolve().as_posix())

    js_script = f"""\
const {{ chromium }} = require('playwright');
(async () => {{
  const browser = await chromium.launch();
  const page = await browser.newPage({{
    viewport: {{ width: {width}, height: {height} }},
    deviceScaleFactor: {scale},
  }});
  await page.goto({html_url_json});
  // Wait for font to load and render to settle.
  await page.waitForTimeout(1000);
  const svg = await page.$('svg');
  if (svg) {{
    await svg.screenshot({{ path: {png_path_json}, omitBackground: true }});
  }} else {{
    await page.screenshot({{ path: {png_path_json}, fullPage: true, omitBackground: true }});
  }}
  await browser.close();
}})();
"""
    tmp_js = repo_root / f".tmp-playwright-render-{os.getpid()}.cjs"
    tmp_js.write_text(js_script, encoding="utf-8")

    try:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("node not found on PATH.")
        result = subprocess.run(
            [node, str(tmp_js)],
            cwd=repo_root,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Playwright render failed (exit={result.returncode}).\n{result.stderr[:1000]}"
            )
        if not png_path.exists():
            raise RuntimeError(f"Playwright did not produce output file: {png_path}")
    finally:
        tmp_js.unlink(missing_ok=True)
        tmp_html.unlink(missing_ok=True)


def compose_stacked_svg(theme_svgs: list[tuple[str, Path]], output_path: Path) -> None:
    """
    Compose a single stacked SVG that visually arranges per-theme SVG captures.

    Creates a composite SVG at output_path that stacks the provided theme SVGs with a staggered, framed layout. Ordering places non-"dark" themes (preserving the order in THEMES) first, appends "dark" last if present, then any remaining themes. All frames are scaled to a common target width (the smallest input width), each frame is drawn on a rectangle using the frame's canvas color, and the original SVG content is embedded as an image for each frame.

    Parameters:
        theme_svgs (list[tuple[str, Path]]): List of (theme_name, svg_path) pairs to include in the composition.
        output_path (Path): Destination path for the generated stacked SVG file.
    """
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
    canvas_colors = [_extract_svg_canvas_color(text) for text in svg_texts]

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
    for i, (svg_text, (width, height), canvas_color) in enumerate(
        zip(svg_texts, scaled_sizes, canvas_colors)
    ):
        x = 30 + i * x_step
        y = 24 + i * y_step
        encoded = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
        lines.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{canvas_color}"/>'
        )
        lines.append(
            f'<image x="{x}" y="{y}" width="{width}" height="{height}" '
            f'preserveAspectRatio="none" href="data:image/svg+xml;base64,{encoded}"/>'
        )
    lines.append("</svg>")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_readme(readme_path: Path, image_path: Path) -> None:
    """
    Update or insert a TUI showcase image block in the given README file.

    If the README already contains the README_START and README_END markers, the function replaces the existing block between them with a new image reference using image_path (POSIX path used in the markdown). If the markers are not present, the function inserts a new "## TUI Showcase" section containing the image block immediately before the "## Install (pip)" anchor if found, otherwise appends the section at the end of the file. The README file is rewritten only when its content would change.

    Parameters:
        readme_path (Path): Path to the README file to update.
        image_path (Path): Path to the image to reference in the README; converted to a POSIX path for the markdown link.
    """
    rel_image = image_path.as_posix()
    block = (
        f"{README_START}\n"
        f"![murmur TUI home across themes]({rel_image})\n"
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
    """
    Generate per-theme TUI showcase image(s) and update the repository README with the generated asset.

    Captures a TUI frame for each configured theme, composes those captures into a stacked showcase image (SVG), optionally rasterizes to PNG, writes the final asset(s) into the configured assets directory, and replaces or inserts the showcase block in the README.

    Returns:
        int: Exit code (0 on success).
    """
    parser = argparse.ArgumentParser(description="Generate TUI showcase images and update README.")
    parser.add_argument("--repo-root", default=".", help="Repository root path")
    parser.add_argument(
        "--assets-dir",
        default="docs/assets",
        help="Directory for generated image assets",
    )
    parser.add_argument("--readme", default="README.md", help="README path")
    parser.add_argument(
        "--capture-seconds",
        default=float(os.environ.get("MURMUR_SHOWCASE_CAPTURE_SECONDS", str(DEFAULT_CAPTURE_SECONDS))),
        type=float,
        help="Seconds to keep TUI alive during each capture",
    )
    parser.add_argument(
        "--output-format",
        choices=[OUTPUT_SVG, OUTPUT_PNG],
        default=os.environ.get("MURMUR_SHOWCASE_OUTPUT_FORMAT", OUTPUT_PNG),
        help=(
            "Final showcase file format. "
            "'png' avoids GitHub SVG renderer differences; "
            "'svg' preserves vector output."
        ),
    )
    parser.add_argument(
        "--png-scale",
        default=float(os.environ.get("MURMUR_SHOWCASE_PNG_SCALE", str(DEFAULT_PNG_SCALE))),
        type=float,
        help="Rasterization scale for PNG output (higher is sharper, larger file).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    assets_dir = (repo_root / args.assets_dir).resolve()
    readme_path = (repo_root / args.readme).resolve()
    output_format = args.output_format
    png_scale = max(1.0, args.png_scale)

    assets_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale in-repo per-theme captures from previous versions.
    for theme in THEMES:
        _clear_capture_target(assets_dir / f"home-{theme}.svg")
        _clear_capture_target(assets_dir / f"home-{theme}.png")

    final_svg = assets_dir / "tui-home-themes.svg"
    final_png = assets_dir / "tui-home-themes.png"

    with tempfile.TemporaryDirectory(
        prefix="murmur-showcase-",
        dir=str(_secure_temp_root(repo_root)),
    ) as temp_dir:
        capture_dir = Path(temp_dir)
        theme_svgs: list[tuple[str, Path]] = []
        for theme in THEMES:
            svg_path = capture_dir / f"home-{theme}.svg"
            attempts = 0
            capture_seconds = max(1.0, args.capture_seconds)
            while True:
                attempts += 1
                try:
                    rendered_svg = run_capture_termtosvg(
                        repo_root=repo_root,
                        theme=theme,
                        port=_pick_capture_port(theme),
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
                        or "Incomplete capture frame detected" in message
                    ):
                        capture_seconds = min(capture_seconds + 1.0, 10.0)
                        continue
                    raise

        stacked_svg = capture_dir / "tui-home-themes.svg"
        _clear_capture_target(stacked_svg)
        compose_stacked_svg(theme_svgs, stacked_svg)

        if output_format == OUTPUT_SVG:
            _clear_capture_target(final_png)
            _clear_capture_target(final_svg)
            shutil.copy2(stacked_svg, final_svg)
            stacked = final_svg
        else:
            _clear_capture_target(final_svg)
            _clear_capture_target(final_png)
            render_svg_to_png(stacked_svg, final_png, png_scale=png_scale, repo_root=repo_root)
            stacked = final_png

    update_readme(readme_path, stacked.relative_to(repo_root))

    print("Generated:")
    print(f"- {stacked.relative_to(repo_root)}")
    if output_format == OUTPUT_PNG:
        print(f"PNG rasterizer: playwright (scale={png_scale:.2f}x)")
    print(f"Updated README: {readme_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
