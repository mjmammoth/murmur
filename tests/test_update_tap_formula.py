from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_update_tap_formula_module():
    """Load the update_tap_formula module."""
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
    """Create a test template file."""
    template = tmp_path / "test.rb.tpl"
    template.write_text(
        'class WhisperLocal < Formula\n'
        '  version "$VERSION"\n'
        '  url "$WHEEL_URL"\n'
        '  sha256 "$WHEEL_SHA256"\n'
        '  resource "tui" do\n'
        '    url "$TUI_URL"\n'
        '    sha256 "$TUI_SHA256"\n'
        '  end\n'
        '  homepage "https://github.com/$REPOSITORY"\n'
        'end\n',
        encoding="utf-8"
    )
    return template


def test_version_pattern_valid_versions(module):
    """Test VERSION_PATTERN matches valid semantic versions."""
    pattern = module.VERSION_PATTERN
    valid_versions = [
        "0.1.0",
        "1.0.0",
        "1.2.3",
        "10.20.30",
        "1.0.0-alpha",
        "1.0.0-beta.1",
        "1.0.0+20130313144700",
        # Note: The regex allows a single prerelease/build metadata segment after the version
        # It doesn't strictly follow semver which allows both prerelease AND build metadata
        # "1.0.0-beta+exp.sha.5114f85" would require a more complex regex
    ]
    for version in valid_versions:
        assert pattern.match(version), f"Version {version} should be valid"


def test_version_pattern_invalid_versions(module):
    """Test VERSION_PATTERN rejects invalid versions."""
    pattern = module.VERSION_PATTERN
    invalid_versions = [
        "1",
        "1.0",
        "v1.0.0",
        "1.0.0.",
        ".1.0.0",
        "1.0.0-",
        "1.0.0+",
        "",
        "abc",
    ]
    for version in invalid_versions:
        assert not pattern.match(version), f"Version {version} should be invalid"


def test_validate_args_valid_input(module, tmp_path: Path):
    """Test validate_args with valid arguments."""
    args = type('Args', (), {
        'version': '1.0.0',
        'repository': 'owner/repo',
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'a' * 64,
        'tui_sha256': 'b' * 64,
    })()

    # Should not raise
    module.validate_args(args)


def test_validate_args_invalid_version(module):
    """Test validate_args rejects invalid version."""
    args = type('Args', (), {
        'version': 'v1.0.0',  # Invalid: has v prefix
        'repository': 'owner/repo',
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'a' * 64,
        'tui_sha256': 'b' * 64,
    })()

    with pytest.raises(ValueError, match="Invalid version"):
        module.validate_args(args)


def test_validate_args_invalid_repository(module):
    """Test validate_args rejects invalid repository."""
    args = type('Args', (), {
        'version': '1.0.0',
        'repository': 'invalid',  # Missing slash
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'a' * 64,
        'tui_sha256': 'b' * 64,
    })()

    with pytest.raises(ValueError, match="Invalid repository"):
        module.validate_args(args)


def test_validate_args_invalid_wheel_url(module):
    """Test validate_args rejects wheel URL not ending in .whl."""
    args = type('Args', (), {
        'version': '1.0.0',
        'repository': 'owner/repo',
        'wheel_url': 'https://example.com/package.tar.gz',  # Wrong extension
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'a' * 64,
        'tui_sha256': 'b' * 64,
    })()

    with pytest.raises(ValueError, match="Expected wheel URL ending in .whl"):
        module.validate_args(args)


def test_validate_args_invalid_tui_url(module):
    """Test validate_args rejects TUI URL not ending in .tar.gz."""
    args = type('Args', (), {
        'version': '1.0.0',
        'repository': 'owner/repo',
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.zip',  # Wrong extension
        'wheel_sha256': 'a' * 64,
        'tui_sha256': 'b' * 64,
    })()

    with pytest.raises(ValueError, match="Expected TUI URL ending in .tar.gz"):
        module.validate_args(args)


def test_validate_args_invalid_wheel_sha256(module):
    """Test validate_args rejects invalid wheel SHA256."""
    args = type('Args', (), {
        'version': '1.0.0',
        'repository': 'owner/repo',
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'invalid',  # Not 64 hex chars
        'tui_sha256': 'b' * 64,
    })()

    with pytest.raises(ValueError, match="Invalid wheel-sha256"):
        module.validate_args(args)


def test_validate_args_invalid_tui_sha256(module):
    """Test validate_args rejects invalid TUI SHA256."""
    args = type('Args', (), {
        'version': '1.0.0',
        'repository': 'owner/repo',
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'a' * 64,
        'tui_sha256': 'ZZZZ',  # Not 64 hex chars
    })()

    with pytest.raises(ValueError, match="Invalid tui-sha256"):
        module.validate_args(args)


def test_render_formula(module, template_file: Path):
    """Test render_formula substitutes template variables correctly."""
    args = type('Args', (), {
        'version': '1.2.3',
        'repository': 'test/repo',
        'wheel_url': 'https://example.com/wheel.whl',
        'wheel_sha256': 'a' * 64,
        'tui_url': 'https://example.com/tui.tar.gz',
        'tui_sha256': 'b' * 64,
        'template': str(template_file),
    })()

    rendered = module.render_formula(args)

    assert '1.2.3' in rendered
    assert 'https://example.com/wheel.whl' in rendered
    assert 'a' * 64 in rendered
    assert 'https://example.com/tui.tar.gz' in rendered
    assert 'b' * 64 in rendered
    assert 'test/repo' in rendered
    assert '$VERSION' not in rendered
    assert '$WHEEL_URL' not in rendered


def test_write_formula(module, tmp_path: Path):
    """Test write_formula creates output file with correct content."""
    rendered = 'class WhisperLocal < Formula\nend\n'
    tap_repo_path = tmp_path / "tap"
    formula_path = Path("Formula/whisper-local.rb")

    output = module.write_formula(rendered, tap_repo_path, formula_path)

    assert output.exists()
    assert output.read_text(encoding="utf-8") == rendered
    assert output == tap_repo_path / formula_path


def test_write_formula_creates_parent_directories(module, tmp_path: Path):
    """Test write_formula creates parent directories if they don't exist."""
    rendered = 'test content'
    tap_repo_path = tmp_path / "tap"
    formula_path = Path("deeply/nested/formula.rb")

    output = module.write_formula(rendered, tap_repo_path, formula_path)

    assert output.exists()
    assert output.parent.exists()
    assert output.read_text(encoding="utf-8") == rendered


def test_main_missing_tap_repo(module, tmp_path: Path, monkeypatch):
    """Test main raises error when tap repo path doesn't exist."""
    nonexistent = tmp_path / "nonexistent"

    args = [
        'script',
        '--version', '1.0.0',
        '--wheel-url', 'https://example.com/wheel.whl',
        '--wheel-sha256', 'a' * 64,
        '--tui-url', 'https://example.com/tui.tar.gz',
        '--tui-sha256', 'b' * 64,
        '--repository', 'owner/repo',
        '--tap-repo-path', str(nonexistent),
    ]

    monkeypatch.setattr(sys, 'argv', args)

    with pytest.raises(FileNotFoundError, match="Tap repo path does not exist"):
        module.main()


def test_parse_args_default_values(module, monkeypatch):
    """Test parse_args uses correct default values."""
    repo_root = Path(__file__).resolve().parents[1]
    default_template = repo_root / "scripts" / "templates" / "whisper-local.rb.tpl"

    args = [
        'script',
        '--version', '1.0.0',
        '--wheel-url', 'https://example.com/wheel.whl',
        '--wheel-sha256', 'a' * 64,
        '--tui-url', 'https://example.com/tui.tar.gz',
        '--tui-sha256', 'b' * 64,
        '--repository', 'owner/repo',
        '--tap-repo-path', '/tmp/tap',
    ]

    monkeypatch.setattr(sys, 'argv', args)

    parsed = module.parse_args()

    assert parsed.version == '1.0.0'
    assert parsed.formula_path == 'Formula/whisper-local.rb'
    assert parsed.template == str(default_template)


def test_sha256_accepts_lowercase_and_uppercase(module):
    """Test that SHA256 validation accepts both lowercase and uppercase hex."""
    args_lower = type('Args', (), {
        'version': '1.0.0',
        'repository': 'owner/repo',
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'abcdef' + '0' * 58,
        'tui_sha256': 'fedcba' + '0' * 58,
    })()

    args_upper = type('Args', (), {
        'version': '1.0.0',
        'repository': 'owner/repo',
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'ABCDEF' + '0' * 58,
        'tui_sha256': 'FEDCBA' + '0' * 58,
    })()

    args_mixed = type('Args', (), {
        'version': '1.0.0',
        'repository': 'owner/repo',
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'AbCdEf' + '0' * 58,
        'tui_sha256': 'FeDcBa' + '0' * 58,
    })()

    # All should be valid
    module.validate_args(args_lower)
    module.validate_args(args_upper)
    module.validate_args(args_mixed)


def test_empty_repository_value_rejected(module):
    """Test that empty repository value is rejected."""
    args = type('Args', (), {
        'version': '1.0.0',
        'repository': '',  # Empty
        'wheel_url': 'https://example.com/package.whl',
        'tui_url': 'https://example.com/tui.tar.gz',
        'wheel_sha256': 'a' * 64,
        'tui_sha256': 'b' * 64,
    })()

    with pytest.raises(ValueError, match="Invalid repository"):
        module.validate_args(args)