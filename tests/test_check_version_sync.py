from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_check_version_sync_module():
    """Load the check_version_sync module."""
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "check_version_sync.py"
    spec = importlib.util.spec_from_file_location("check_version_sync", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module():
    return _load_check_version_sync_module()


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[1]


def test_project_versions_are_synchronized(module, repo_root) -> None:
    """Test that pyproject.toml and __init__.py versions match."""
    pyproject_version = module.read_pyproject_version(repo_root / "pyproject.toml")
    init_version = module.read_init_version(repo_root / "src" / "whisper_local" / "__init__.py")
    assert pyproject_version == init_version


def test_read_pyproject_version_success(module, tmp_path: Path) -> None:
    """Test read_pyproject_version reads version correctly."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "test-package"\n'
        'version = "1.2.3"\n',
        encoding="utf-8"
    )

    version = module.read_pyproject_version(pyproject)
    assert version == "1.2.3"


def test_read_pyproject_version_missing_project_section(module, tmp_path: Path) -> None:
    """Test read_pyproject_version raises error when [project] section missing."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.pytest]\n'
        'testpaths = ["tests"]\n',
        encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Unable to read \\[project\\].version"):
        module.read_pyproject_version(pyproject)


def test_read_pyproject_version_missing_version_key(module, tmp_path: Path) -> None:
    """Test read_pyproject_version raises error when version key missing."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "test-package"\n',
        encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Unable to read \\[project\\].version"):
        module.read_pyproject_version(pyproject)


def test_read_init_version_success(module, tmp_path: Path) -> None:
    """Test read_init_version reads version correctly."""
    init_file = tmp_path / "__init__.py"
    init_file.write_text(
        '__version__ = "2.3.4"\n'
        '__all__ = ["__version__"]\n',
        encoding="utf-8"
    )

    version = module.read_init_version(init_file)
    assert version == "2.3.4"


def test_read_init_version_with_single_quotes(module, tmp_path: Path) -> None:
    """Test read_init_version handles single quotes."""
    init_file = tmp_path / "__init__.py"
    init_file.write_text(
        "__version__ = '3.4.5'\n",
        encoding="utf-8"
    )

    # The regex looks for double quotes, so this should fail
    with pytest.raises(ValueError, match="Unable to find __version__"):
        module.read_init_version(init_file)


def test_read_init_version_missing_version(module, tmp_path: Path) -> None:
    """Test read_init_version raises error when __version__ missing."""
    init_file = tmp_path / "__init__.py"
    init_file.write_text(
        '__all__ = ["something"]\n',
        encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Unable to find __version__"):
        module.read_init_version(init_file)


def test_read_init_version_commented_version(module, tmp_path: Path) -> None:
    """Test read_init_version ignores commented __version__."""
    init_file = tmp_path / "__init__.py"
    init_file.write_text(
        '# __version__ = "0.0.1"\n'
        '__version__ = "1.0.0"\n',
        encoding="utf-8"
    )

    version = module.read_init_version(init_file)
    assert version == "1.0.0"


def test_main_returns_zero_on_match(module, tmp_path: Path, monkeypatch) -> None:
    """Test main returns 0 when versions match."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'version = "1.0.0"\n',
        encoding="utf-8"
    )

    init_file = tmp_path / "__init__.py"
    init_file.write_text(
        '__version__ = "1.0.0"\n',
        encoding="utf-8"
    )

    args = [
        'script',
        '--pyproject', str(pyproject),
        '--init-file', str(init_file)
    ]
    monkeypatch.setattr(sys, 'argv', args)

    result = module.main()
    assert result == 0


def test_main_returns_one_on_mismatch(module, tmp_path: Path, monkeypatch, capsys) -> None:
    """Test main returns 1 when versions don't match."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'version = "1.0.0"\n',
        encoding="utf-8"
    )

    init_file = tmp_path / "__init__.py"
    init_file.write_text(
        '__version__ = "2.0.0"\n',
        encoding="utf-8"
    )

    args = [
        'script',
        '--pyproject', str(pyproject),
        '--init-file', str(init_file)
    ]
    monkeypatch.setattr(sys, 'argv', args)

    result = module.main()
    assert result == 1

    captured = capsys.readouterr()
    assert 'Version mismatch detected' in captured.err
    assert '1.0.0' in captured.err
    assert '2.0.0' in captured.err


def test_main_prints_success_message(module, tmp_path: Path, monkeypatch, capsys) -> None:
    """Test main prints success message when versions match."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'version = "5.6.7"\n',
        encoding="utf-8"
    )

    init_file = tmp_path / "__init__.py"
    init_file.write_text(
        '__version__ = "5.6.7"\n',
        encoding="utf-8"
    )

    args = [
        'script',
        '--pyproject', str(pyproject),
        '--init-file', str(init_file)
    ]
    monkeypatch.setattr(sys, 'argv', args)

    result = module.main()
    assert result == 0

    captured = capsys.readouterr()
    assert 'Version sync OK: 5.6.7' in captured.out


def test_parse_args_defaults(module, monkeypatch) -> None:
    """Test parse_args uses default file paths."""
    args = ['script']
    monkeypatch.setattr(sys, 'argv', args)

    parsed = module.parse_args()
    assert parsed.pyproject == 'pyproject.toml'
    assert parsed.init_file == 'src/whisper_local/__init__.py'


def test_parse_args_custom_paths(module, monkeypatch) -> None:
    """Test parse_args accepts custom file paths."""
    args = [
        'script',
        '--pyproject', '/custom/pyproject.toml',
        '--init-file', '/custom/__init__.py'
    ]
    monkeypatch.setattr(sys, 'argv', args)

    parsed = module.parse_args()
    assert parsed.pyproject == '/custom/pyproject.toml'
    assert parsed.init_file == '/custom/__init__.py'


def test_read_init_version_multiline_before_version(module, tmp_path: Path) -> None:
    """Test read_init_version finds __version__ in multiline file."""
    init_file = tmp_path / "__init__.py"
    init_file.write_text(
        '"""Module docstring."""\n'
        '\n'
        'from typing import Any\n'
        '\n'
        '__version__ = "7.8.9"\n'
        '\n'
        '__all__ = ["__version__"]\n',
        encoding="utf-8"
    )

    version = module.read_init_version(init_file)
    assert version == "7.8.9"


def test_read_pyproject_version_returns_string(module, tmp_path: Path) -> None:
    """Test read_pyproject_version returns string type."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'version = "1.0.0"\n',
        encoding="utf-8"
    )

    version = module.read_pyproject_version(pyproject)
    assert isinstance(version, str)