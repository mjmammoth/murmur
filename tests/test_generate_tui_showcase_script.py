from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


def _load_generate_tui_showcase_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "generate_tui_showcase.py"
    spec = importlib.util.spec_from_file_location("generate_tui_showcase", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module():
    return _load_generate_tui_showcase_module()


def test_generate_tui_showcase_script_uses_secure_temp_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "generate_tui_showcase.py").read_text(encoding="utf-8")

    assert "def _secure_temp_root(repo_root: Path) -> Path:" in script
    assert 'prefix="murmur-showcase-"' in script
    assert "dir=str(_secure_temp_root(repo_root))" in script


def test_generate_tui_showcase_script_pins_font_source_and_checksum() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "generate_tui_showcase.py").read_text(encoding="utf-8")

    assert "FONT_TTF_SHA256 = " in script
    assert "raw.githubusercontent.com/ryanoasis/nerd-fonts/" in script
    assert "ae57d27445e9d85db49fc917c5276c5d249109c8" in script
    assert "Downloaded font checksum mismatch." in script
    assert "def _sha256_file(path: Path) -> str:" in script


def test_showcase_requirements_are_pinned() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    requirements = (
        repo_root / "scripts" / "requirements-tui-showcase.txt"
    ).read_text(encoding="utf-8")

    lines = [line.strip() for line in requirements.splitlines() if line.strip()]
    assert lines
    assert all("==" in line for line in lines)


def test_extract_transcript_item_count_finds_single_item(module) -> None:
    """Test extraction of single item count from text."""
    text = "Transcripts: 1 item"
    count = module._extract_transcript_item_count(text)
    assert count == 1


def test_extract_transcript_item_count_finds_multiple_items(module) -> None:
    """Test extraction of multiple items count from text."""
    text = "Transcripts: 42 items"
    count = module._extract_transcript_item_count(text)
    assert count == 42


def test_extract_transcript_item_count_finds_max_count(module) -> None:
    """Test that max count is returned when multiple counts present."""
    text = "Found 5 items, later 3 items, and finally 10 items total"
    count = module._extract_transcript_item_count(text)
    assert count == 10


def test_extract_transcript_item_count_returns_zero_when_no_items(module) -> None:
    """Test that zero is returned when no item counts found."""
    text = "No transcript data found"
    count = module._extract_transcript_item_count(text)
    assert count == 0


def test_extract_transcript_item_count_handles_whitespace(module) -> None:
    """Test that item count extraction handles various whitespace."""
    text = "Status:   123  item"
    count = module._extract_transcript_item_count(text)
    assert count == 123


def test_is_port_available_returns_true_for_available_port(module) -> None:
    """Test that _is_port_available returns True for an available port."""
    # Port 0 should always be available as it lets the OS choose
    assert module._is_port_available(0) is True


def test_is_port_available_handles_permission_error(module) -> None:
    """Test that _is_port_available handles permission errors gracefully."""
    with patch("socket.socket") as mock_socket:
        mock_socket.return_value.__enter__.return_value.bind.side_effect = PermissionError()
        result = module._is_port_available(80)
        assert result is False


def test_clear_capture_target_removes_file(module, tmp_path: Path) -> None:
    """Test that _clear_capture_target removes existing files."""
    test_file = tmp_path / "test.svg"
    test_file.write_text("content", encoding="utf-8")
    assert test_file.exists()

    module._clear_capture_target(test_file)
    assert not test_file.exists()


def test_clear_capture_target_removes_directory(module, tmp_path: Path) -> None:
    """Test that _clear_capture_target removes directories recursively."""
    test_dir = tmp_path / "test_dir"
    test_dir.mkdir()
    (test_dir / "file.txt").write_text("content", encoding="utf-8")
    assert test_dir.exists()

    module._clear_capture_target(test_dir)
    assert not test_dir.exists()


def test_clear_capture_target_handles_nonexistent_path(module, tmp_path: Path) -> None:
    """Test that _clear_capture_target handles nonexistent paths gracefully."""
    nonexistent = tmp_path / "nonexistent"
    # Should not raise
    module._clear_capture_target(nonexistent)


def test_looks_blank_capture_returns_true_for_blank_svg(module, tmp_path: Path) -> None:
    """Test that blank SVG (few text elements) is detected."""
    svg_path = tmp_path / "blank.svg"
    svg_content = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg">
  <text>Small</text>
</svg>"""
    svg_path.write_text(svg_content, encoding="utf-8")

    assert module._looks_blank_capture(svg_path) is True


def test_looks_blank_capture_returns_false_for_populated_svg(module, tmp_path: Path) -> None:
    """Test that populated SVG (many text elements) is not blank."""
    svg_path = tmp_path / "populated.svg"
    text_elements = "\n".join([f"<text>Line {i}</text>" for i in range(20)])
    svg_content = f"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg">
  {text_elements}
</svg>"""
    svg_path.write_text(svg_content, encoding="utf-8")

    assert module._looks_blank_capture(svg_path) is False


def test_svg_dimensions_parses_viewbox(module) -> None:
    """Test SVG dimension extraction from viewBox attribute."""
    svg_text = '<svg viewBox="0 0 1200 800"></svg>'
    width, height = module._svg_dimensions(svg_text)
    assert width == 1200
    assert height == 800


def test_svg_dimensions_parses_width_height_attributes(module) -> None:
    """Test SVG dimension extraction from width/height attributes."""
    svg_text = '<svg width="640" height="480"></svg>'
    width, height = module._svg_dimensions(svg_text)
    assert width == 640
    assert height == 480


def test_svg_dimensions_returns_defaults_for_invalid_svg(module) -> None:
    """Test that default dimensions are returned for invalid SVG."""
    svg_text = '<svg></svg>'
    width, height = module._svg_dimensions(svg_text)
    assert width == 960
    assert height == 546


def test_svg_dimensions_handles_float_values(module) -> None:
    """Test that float dimension values are converted to int."""
    svg_text = '<svg viewBox="0 0 1200.5 800.7"></svg>'
    width, height = module._svg_dimensions(svg_text)
    assert width == 1200
    assert height == 800


def test_extract_svg_canvas_color_finds_rect_at_origin(module) -> None:
    """Test canvas color extraction from rectangle at origin."""
    svg_text = '''<svg>
  <g>
    <rect x="0" y="0" fill="#282828"/>
  </g>
</svg>'''
    color = module._extract_svg_canvas_color(svg_text)
    assert color == "#282828"


def test_extract_svg_canvas_color_returns_default_when_not_found(module) -> None:
    """Test that default color is returned when canvas rect not found."""
    svg_text = '<svg><rect x="10" y="10" fill="#ff0000"/></svg>'
    color = module._extract_svg_canvas_color(svg_text)
    assert color == "#0c0c0c"


def test_resolve_svg_capture_returns_file_when_path_is_file(module, tmp_path: Path) -> None:
    """Test that _resolve_svg_capture returns the path when it's a file."""
    svg_file = tmp_path / "capture.svg"
    svg_file.write_text("<svg></svg>", encoding="utf-8")

    result = module._resolve_svg_capture(svg_file)
    assert result == svg_file


def test_resolve_svg_capture_finds_svg_in_directory(module, tmp_path: Path) -> None:
    """Test that _resolve_svg_capture finds SVG files in a directory."""
    svg_dir = tmp_path / "captures"
    svg_dir.mkdir()
    (svg_dir / "frame1.svg").write_text("<svg><text>Test</text></svg>", encoding="utf-8")

    result = module._resolve_svg_capture(svg_dir)
    assert result.name == "frame1.svg"


def test_resolve_svg_capture_prefers_populated_frames(module, tmp_path: Path) -> None:
    """Test that _resolve_svg_capture prefers frames with more content."""
    svg_dir = tmp_path / "captures"
    svg_dir.mkdir()

    # Create a blank frame
    blank_svg = "<svg><text>A</text></svg>"
    (svg_dir / "frame1.svg").write_text(blank_svg, encoding="utf-8")

    # Create a populated frame with "Ready" marker and items
    populated_svg = (
        "<svg>"
        + "".join(f"<text>Line {i}</text>" for i in range(15))
        + "<text>Ready</text>"
        + "<text>large-v3-turbo</text>"
        + "<text>4 items</text>"
        + "<text>Transcripts</text>"
        + "</svg>"
    )
    (svg_dir / "frame2.svg").write_text(populated_svg, encoding="utf-8")

    result = module._resolve_svg_capture(svg_dir)
    assert result.name == "frame2.svg"


def test_resolve_svg_capture_raises_when_path_not_found(module, tmp_path: Path) -> None:
    """Test that _resolve_svg_capture raises when no SVG found."""
    nonexistent = tmp_path / "missing"

    with pytest.raises(FileNotFoundError, match="Could not find rendered SVG"):
        module._resolve_svg_capture(nonexistent)


def test_sanitize_termtosvg_svg_removes_underline_attribute(module, tmp_path: Path) -> None:
    """Test that underline text-decoration is removed from SVG."""
    svg_path = tmp_path / "test.svg"
    svg_content = '<text text-decoration="underline">Hello</text>'
    svg_path.write_text(svg_content, encoding="utf-8")

    module._sanitize_termtosvg_svg(svg_path)

    result = svg_path.read_text(encoding="utf-8")
    assert 'text-decoration="underline"' not in result
    assert "<text" in result


def test_sanitize_termtosvg_svg_preserves_content_without_underline(module, tmp_path: Path) -> None:
    """Test that SVG without underline is unchanged."""
    svg_path = tmp_path / "test.svg"
    svg_content = '<text fill="white">Hello</text>'
    svg_path.write_text(svg_content, encoding="utf-8")

    module._sanitize_termtosvg_svg(svg_path)

    result = svg_path.read_text(encoding="utf-8")
    assert result == svg_content


def test_sha256_file_computes_correct_hash(module, tmp_path: Path) -> None:
    """Test that SHA256 hash is correctly computed for a file."""
    test_file = tmp_path / "test.txt"
    test_file.write_bytes(b"Hello, World!")

    result = module._sha256_file(test_file)

    # Known SHA256 hash of "Hello, World!"
    expected = "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"
    assert result == expected


def test_wait_for_server_returns_true_when_server_responds(module) -> None:
    """Test that _wait_for_server returns True when server is up."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__ = Mock()
        mock_urlopen.return_value.__exit__ = Mock()

        result = module._wait_for_server(8080, timeout=0.5, interval=0.1)
        assert result is True


def test_wait_for_server_returns_false_on_timeout(module) -> None:
    """Test that _wait_for_server returns False when timeout is reached."""
    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        result = module._wait_for_server(8080, timeout=0.2, interval=0.1)
        assert result is False


def test_pick_capture_port_returns_available_port(module) -> None:
    """Test that _pick_capture_port returns an available port."""
    port = module._pick_capture_port("dark")
    # Just verify it's in the valid range
    assert 1024 < port < 65535


def test_pick_capture_port_uses_theme_specific_base(module) -> None:
    """Test that different themes get different base ports."""
    with patch.object(module, "_is_port_available", return_value=True):
        dark_port = module._pick_capture_port("dark")
        light_port = module._pick_capture_port("light")

        # Should return different base ports
        assert dark_port != light_port


def test_update_readme_inserts_showcase_block(module, tmp_path: Path) -> None:
    """Test that update_readme inserts showcase block when not present."""
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nSome content\n", encoding="utf-8")
    image_path = Path("docs/assets/showcase.png")

    module.update_readme(readme, image_path)

    content = readme.read_text(encoding="utf-8")
    assert "<!-- tui-showcase:start -->" in content
    assert "![murmur TUI home across themes](docs/assets/showcase.png)" in content
    assert "<!-- tui-showcase:end -->" in content


def test_update_readme_replaces_existing_showcase_block(module, tmp_path: Path) -> None:
    """Test that update_readme replaces existing showcase block."""
    readme = tmp_path / "README.md"
    original_content = """# Project

<!-- tui-showcase:start -->
![old image](old.png)
<!-- tui-showcase:end -->

More content
"""
    readme.write_text(original_content, encoding="utf-8")
    image_path = Path("docs/assets/new.png")

    module.update_readme(readme, image_path)

    content = readme.read_text(encoding="utf-8")
    assert "![murmur TUI home across themes](docs/assets/new.png)" in content
    assert "old.png" not in content
