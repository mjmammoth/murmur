from __future__ import annotations

from pathlib import Path

from whisper_local.config import load_config, save_config


def test_load_config_ignores_legacy_model_auto_download(tmp_path: Path) -> None:
    """Legacy model.auto_download should not break config loading."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[model]
name = "base"
runtime = "whisper.cpp"
auto_download = true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.model.name == "base"
    assert config.model.runtime == "whisper.cpp"
    assert not hasattr(config.model, "auto_download")


def test_save_config_drops_legacy_model_auto_download(tmp_path: Path) -> None:
    """Legacy model.auto_download should be omitted when saving config."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[model]
name = "small"
runtime = "faster-whisper"
auto_download = true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(config_path)
    save_config(config, config_path)

    written = config_path.read_text(encoding="utf-8")
    assert "auto_download" not in written


def test_load_config_defaults_auto_revert_clipboard_true(tmp_path: Path) -> None:
    """
    Verify that when a config file omits `auto_revert_clipboard`, the loaded configuration enables auto-reverting the clipboard by default.
    """
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
auto_copy = false
auto_paste = true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.auto_revert_clipboard is True