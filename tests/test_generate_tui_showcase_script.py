from __future__ import annotations

from pathlib import Path


def test_generate_tui_showcase_script_uses_secure_temp_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "generate_tui_showcase.py").read_text(encoding="utf-8")

    assert "def _secure_temp_root(repo_root: Path) -> Path:" in script
    assert 'prefix="whisper-local-showcase-"' in script
    assert "dir=str(_secure_temp_root(repo_root))" in script
