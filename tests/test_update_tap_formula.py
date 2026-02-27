from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_update_tap_formula_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "update_tap_formula.py"
    spec = importlib.util.spec_from_file_location("update_tap_formula", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module():
    return _load_update_tap_formula_module()


@pytest.fixture
def template_file(tmp_path: Path) -> Path:
    template = tmp_path / "test.rb.tpl"
    template.write_text(
        'class WhisperLocal < Formula\n'
        '  url "$WHEEL_URL"\n'
        '  sha256 "$WHEEL_SHA256"\n'
        '  darwin_arm_url "$TUI_URL_DARWIN_ARM64"\n'
        '  darwin_x64_url "$TUI_URL_DARWIN_X64"\n'
        '  linux_x64_url "$TUI_URL_LINUX_X64"\n'
        '  linux_arm_url "$TUI_URL_LINUX_ARM64"\n'
        '  homepage "https://github.com/$REPOSITORY"\n'
        'end\n',
        encoding="utf-8",
    )
    return template


def _base_args(**overrides):
    payload = {
        "version": "1.0.0",
        "repository": "owner/repo",
        "wheel_url": "https://example.com/package.whl",
        "wheel_sha256": "a" * 64,
        "tui_url": "https://example.com/tui.tar.gz",
        "tui_sha256": "b" * 64,
        "tui_url_darwin_arm64": "",
        "tui_sha256_darwin_arm64": "",
        "tui_url_darwin_x64": "",
        "tui_sha256_darwin_x64": "",
        "tui_url_linux_x64": "",
        "tui_sha256_linux_x64": "",
        "tui_url_linux_arm64": "",
        "tui_sha256_linux_arm64": "",
    }
    payload.update(overrides)
    return type("Args", (), payload)()


def test_version_pattern_valid_versions(module):
    pattern = module.VERSION_PATTERN
    assert pattern.match("0.1.0")
    assert pattern.match("1.2.3")
    assert pattern.match("1.0.0-alpha")


def test_validate_args_accepts_legacy_tui_values(module):
    args = _base_args()

    module.validate_args(args)

    assert args.tui_url_darwin_arm64 == args.tui_url
    assert args.tui_url_darwin_x64 == args.tui_url
    assert args.tui_url_linux_x64 == args.tui_url
    assert args.tui_url_linux_arm64 == args.tui_url


def test_validate_args_accepts_per_target_tui_values(module):
    args = _base_args(
        tui_url="",
        tui_sha256="",
        tui_url_darwin_arm64="https://example.com/darwin-arm64.tar.gz",
        tui_sha256_darwin_arm64="1" * 64,
        tui_url_darwin_x64="https://example.com/darwin-x64.tar.gz",
        tui_sha256_darwin_x64="2" * 64,
        tui_url_linux_x64="https://example.com/linux-x64.tar.gz",
        tui_sha256_linux_x64="3" * 64,
        tui_url_linux_arm64="https://example.com/linux-arm64.tar.gz",
        tui_sha256_linux_arm64="4" * 64,
    )

    module.validate_args(args)


def test_validate_args_rejects_invalid_tui_target_url(module):
    args = _base_args(
        tui_url="",
        tui_sha256="",
        tui_url_darwin_arm64="https://example.com/darwin-arm64.zip",
        tui_sha256_darwin_arm64="1" * 64,
        tui_url_darwin_x64="https://example.com/darwin-x64.tar.gz",
        tui_sha256_darwin_x64="2" * 64,
        tui_url_linux_x64="https://example.com/linux-x64.tar.gz",
        tui_sha256_linux_x64="3" * 64,
        tui_url_linux_arm64="https://example.com/linux-arm64.tar.gz",
        tui_sha256_linux_arm64="4" * 64,
    )

    with pytest.raises(ValueError, match="Expected TUI URL ending in .tar.gz"):
        module.validate_args(args)


def test_validate_args_rejects_invalid_tui_target_sha(module):
    args = _base_args(
        tui_url="",
        tui_sha256="",
        tui_url_darwin_arm64="https://example.com/darwin-arm64.tar.gz",
        tui_sha256_darwin_arm64="bad",
        tui_url_darwin_x64="https://example.com/darwin-x64.tar.gz",
        tui_sha256_darwin_x64="2" * 64,
        tui_url_linux_x64="https://example.com/linux-x64.tar.gz",
        tui_sha256_linux_x64="3" * 64,
        tui_url_linux_arm64="https://example.com/linux-arm64.tar.gz",
        tui_sha256_linux_arm64="4" * 64,
    )

    with pytest.raises(ValueError, match="Invalid tui-sha256-darwin-arm64"):
        module.validate_args(args)


def test_render_formula_substitutes_per_target_variables(module, template_file: Path):
    args = _base_args(
        template=str(template_file),
        tui_url_darwin_arm64="https://example.com/darwin-arm64.tar.gz",
        tui_sha256_darwin_arm64="1" * 64,
        tui_url_darwin_x64="https://example.com/darwin-x64.tar.gz",
        tui_sha256_darwin_x64="2" * 64,
        tui_url_linux_x64="https://example.com/linux-x64.tar.gz",
        tui_sha256_linux_x64="3" * 64,
        tui_url_linux_arm64="https://example.com/linux-arm64.tar.gz",
        tui_sha256_linux_arm64="4" * 64,
    )

    rendered = module.render_formula(args)

    assert "https://example.com/package.whl" in rendered
    assert "https://example.com/darwin-arm64.tar.gz" in rendered
    assert "https://example.com/darwin-x64.tar.gz" in rendered
    assert "https://example.com/linux-x64.tar.gz" in rendered
    assert "https://example.com/linux-arm64.tar.gz" in rendered


def test_render_formula_uses_secure_python_extraction(module) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    args = _base_args(
        template=str(repo_root / "scripts" / "templates" / "whisper-local.rb.tpl"),
        tui_url_darwin_arm64="https://example.com/darwin-arm64.tar.gz",
        tui_sha256_darwin_arm64="1" * 64,
        tui_url_darwin_x64="https://example.com/darwin-x64.tar.gz",
        tui_sha256_darwin_x64="2" * 64,
        tui_url_linux_x64="https://example.com/linux-x64.tar.gz",
        tui_sha256_linux_x64="3" * 64,
        tui_url_linux_arm64="https://example.com/linux-arm64.tar.gz",
        tui_sha256_linux_arm64="4" * 64,
    )

    rendered = module.render_formula(args)

    assert "install_tui_binary_from_archive" in rendered
    assert 'system "tar", "-xzf"' not in rendered


def test_write_formula(module, tmp_path: Path):
    rendered = "class WhisperLocal < Formula\nend\n"
    tap_repo_path = tmp_path / "tap"
    formula_path = Path("Formula/whisper-local.rb")

    output = module.write_formula(rendered, tap_repo_path, formula_path)

    assert output.exists()
    assert output.read_text(encoding="utf-8") == rendered


def test_main_missing_tap_repo(module, tmp_path: Path, monkeypatch):
    nonexistent = tmp_path / "missing"
    args = [
        "script",
        "--version",
        "1.0.0",
        "--wheel-url",
        "https://example.com/wheel.whl",
        "--wheel-sha256",
        "a" * 64,
        "--tui-url",
        "https://example.com/tui.tar.gz",
        "--tui-sha256",
        "b" * 64,
        "--repository",
        "owner/repo",
        "--tap-repo-path",
        str(nonexistent),
    ]
    monkeypatch.setattr(sys, "argv", args)

    with pytest.raises(FileNotFoundError, match="Tap repo path does not exist"):
        module.main()


def test_parse_args_defaults(module, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    default_template = repo_root / "scripts" / "templates" / "whisper-local.rb.tpl"

    args = [
        "script",
        "--version",
        "1.0.0",
        "--wheel-url",
        "https://example.com/wheel.whl",
        "--wheel-sha256",
        "a" * 64,
        "--tui-url",
        "https://example.com/tui.tar.gz",
        "--tui-sha256",
        "b" * 64,
        "--repository",
        "owner/repo",
        "--tap-repo-path",
        "/var/lib/whisper-local/tap",
    ]
    monkeypatch.setattr(sys, "argv", args)

    parsed = module.parse_args()

    assert parsed.template == str(default_template)
    assert parsed.formula_path == "Formula/whisper-local.rb"
