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


def test_load_config_defaults_audio_input_device_none(tmp_path: Path) -> None:
    """Missing audio.input_device should default to None."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[audio]
sample_rate = 16000
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.audio.input_device is None


def test_save_config_round_trip_audio_input_device(tmp_path: Path) -> None:
    """Explicit audio.input_device should survive save/load round trips."""
    config_path = tmp_path / "config.toml"
    config = load_config(config_path)
    config.audio.input_device = "CoreAudio:Built-in Microphone"

    save_config(config, config_path)
    reloaded = load_config(config_path)

    assert reloaded.audio.input_device == "CoreAudio:Built-in Microphone"


def test_save_config_omits_none_audio_input_device(tmp_path: Path) -> None:
    """None audio.input_device should not be written to disk."""
    config_path = tmp_path / "config.toml"
    config = load_config(config_path)
    config.audio.input_device = None

    save_config(config, config_path)
    written = config_path.read_text(encoding="utf-8")

    assert "input_device" not in written


def test_load_config_history_defaults_to_5000(tmp_path: Path) -> None:
    """Missing history config should default max_entries to 5000."""
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    config = load_config(config_path)

    assert config.history.max_entries == 5000


def test_load_config_history_max_entries_is_clamped(tmp_path: Path) -> None:
    """history.max_entries should always be a positive integer."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[history]
max_entries = 0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.history.max_entries == 1
