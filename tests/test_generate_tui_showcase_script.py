from __future__ import annotations

from pathlib import Path


def test_generate_tui_showcase_script_uses_secure_temp_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "generate_tui_showcase.py").read_text(encoding="utf-8")

    assert "def _secure_temp_root(repo_root: Path) -> Path:" in script
    assert 'prefix="whisper-local-showcase-"' in script
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
