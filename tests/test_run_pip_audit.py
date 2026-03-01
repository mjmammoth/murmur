from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def run_pip_audit_script(repo_root: Path) -> Path:
    return repo_root / "scripts" / "ci" / "run_pip_audit.sh"


def test_run_pip_audit_script_exists(run_pip_audit_script: Path) -> None:
    """Test that the run_pip_audit.sh script exists."""
    assert run_pip_audit_script.exists()
    assert run_pip_audit_script.is_file()


def test_run_pip_audit_script_has_bash_shebang(run_pip_audit_script: Path) -> None:
    """Test that script has correct bash shebang."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert content.startswith("#!/usr/bin/env bash")


def test_run_pip_audit_script_uses_ignore_file(run_pip_audit_script: Path) -> None:
    """Test that script references the ignore file."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert "configs/security/pip-audit-ignore.txt" in content
    assert "--ignore-vuln" in content


def test_run_pip_audit_script_filters_murmur(run_pip_audit_script: Path) -> None:
    """Test that script filters out murmur package from requirements."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    # Should filter out murmur from pip freeze output
    assert "murmur" in content
    assert "awk" in content or "grep" in content


def test_run_pip_audit_script_uses_pip_freeze(run_pip_audit_script: Path) -> None:
    """Test that script uses pip freeze to get requirements."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert "pip freeze" in content or "pip_freeze" in content.replace(" ", "_")


def test_run_pip_audit_script_uses_strict_mode(run_pip_audit_script: Path) -> None:
    """Test that script runs pip-audit in strict mode."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert "--strict" in content


def test_run_pip_audit_script_skips_editable(run_pip_audit_script: Path) -> None:
    """Test that script skips editable packages."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert "--skip-editable" in content


def test_run_pip_audit_script_uses_requirements_file(run_pip_audit_script: Path) -> None:
    """Test that script uses -r flag for requirements file."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert " -r " in content or '"-r"' in content


def test_run_pip_audit_script_reads_ignore_file_lines(run_pip_audit_script: Path) -> None:
    """Test that script reads ignore file line by line."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert "while IFS=" in content or "read -r" in content


def test_run_pip_audit_script_strips_comments(run_pip_audit_script: Path) -> None:
    """Test that script strips comments from ignore file."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    # Should strip trailing comments using bash parameter expansion
    assert '${line%%#*}' in content


def test_run_pip_audit_script_handles_empty_lines(run_pip_audit_script: Path) -> None:
    """Test that script handles empty lines in ignore file."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    # Should guard against empty lines with a non-empty test before appending
    assert '[[ -n "${line}" ]]' in content
    # Should trim whitespace from lines (via xargs)
    assert "xargs" in content


def test_run_pip_audit_script_respects_python_env_var(run_pip_audit_script: Path) -> None:
    """Test that script respects PYTHON environment variable."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert "PYTHON" in content


def test_run_pip_audit_script_has_error_handling(run_pip_audit_script: Path) -> None:
    """Test that script uses bash error handling."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    # Should have set -euo pipefail for strict error handling
    assert "set -euo pipefail" in content or "set -e" in content


def test_run_pip_audit_script_syntax_is_valid(
    run_pip_audit_script: Path, repo_root: Path
) -> None:
    """Test that script has valid bash syntax using bash -n."""
    result = subprocess.run(
        ["bash", "-n", str(run_pip_audit_script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Syntax errors: {result.stderr}"


def test_ignore_file_format(repo_root: Path) -> None:
    """Test that pip-audit-ignore.txt has correct format."""
    ignore_file = repo_root / "configs" / "security" / "pip-audit-ignore.txt"
    assert ignore_file.exists()

    content = ignore_file.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]

    # All non-empty, non-comment lines should be vulnerability IDs
    for line in lines:
        if line and not line.startswith("#"):
            # Vulnerability IDs typically start with GHSA-, CVE-, or similar
            assert (
                line.startswith("GHSA-")
                or line.startswith("CVE-")
                or line.startswith("PYSEC-")
            ), f"Invalid vulnerability ID format: {line}"


def test_run_pip_audit_script_creates_temp_requirements(run_pip_audit_script: Path) -> None:
    """Test that script creates a temporary requirements file."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert "mktemp" in content
    assert "TMP_REQUIREMENTS" in content or "tmp" in content.lower()


def test_run_pip_audit_script_has_cleanup_trap(run_pip_audit_script: Path) -> None:
    """Test that script has cleanup trap for temporary files."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    assert "trap" in content


def test_run_pip_audit_script_builds_ignore_args_array(run_pip_audit_script: Path) -> None:
    """Test that script builds an array of ignore arguments."""
    content = run_pip_audit_script.read_text(encoding="utf-8")
    # Should declare and populate ignore_args array
    assert "ignore_args" in content
    assert "+=" in content  # Array append operator
