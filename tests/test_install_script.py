from __future__ import annotations

from pathlib import Path


def test_install_script_uses_secure_python_archive_extraction() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    install_script = (repo_root / "install").read_text(encoding="utf-8")

    assert 'tar -xzf "${tui_archive_path}" -C "${TUI_ROOT}/${target}"' not in install_script
    assert "install_tui_binary_from_archive(" in install_script
    assert "command -v tar" not in install_script
