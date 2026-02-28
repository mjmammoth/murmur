from __future__ import annotations

from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import logging

import tomllib
import tomli_w


logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    name: str = "small"
    runtime: str = "faster-whisper"
    device: str = "cpu"
    compute_type: str = "int8"
    path: str | None = None
    language: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelConfig:
        """
        Construct a ModelConfig from a dictionary of configuration values.

        Parameters:
            data (dict[str, Any]): Mapping containing optional keys: "name", "runtime", "device",
                "compute_type", "path", and "language". Missing keys are replaced with defaults.

        Returns:
            ModelConfig: Instance populated from `data`. The `runtime` value is normalized before assignment.
        """
        return cls(
            name=data.get("name", "small"),
            runtime=normalize_runtime_name(str(data.get("runtime", "faster-whisper"))),
            device=data.get("device", "cpu"),
            compute_type=data.get("compute_type", "int8"),
            path=data.get("path"),
            language=data.get("language"),
        )


@dataclass
class HotkeyConfig:
    mode: str = "ptt"
    key: str = "f3"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HotkeyConfig:
        return cls(
            mode=data.get("mode", "ptt"),
            key=data.get("key", "f3"),
        )


@dataclass
class NoiseSuppressionConfig:
    enabled: bool = True
    level: int = 2

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NoiseSuppressionConfig:
        return cls(
            enabled=data.get("enabled", True),
            level=data.get("level", 2),
        )


@dataclass
class AudioConfig:
    sample_rate: int = 48000
    input_device: str | None = None
    noise_suppression: NoiseSuppressionConfig = field(default_factory=NoiseSuppressionConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioConfig:
        raw_input_device = data.get("input_device")
        normalized_input_device: str | None
        if raw_input_device is None:
            normalized_input_device = None
        else:
            trimmed = str(raw_input_device).strip()
            normalized_input_device = trimmed or None
        return cls(
            sample_rate=data.get("sample_rate", 48000),
            input_device=normalized_input_device,
            noise_suppression=NoiseSuppressionConfig.from_dict(
                data.get("noise_suppression", {})
            ),
        )


@dataclass
class VadConfig:
    enabled: bool = False
    aggressiveness: int = 1
    min_speech_ms: int = 200
    max_silence_ms: int = 600

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VadConfig:
        return cls(
            enabled=data.get("enabled", False),
            aggressiveness=data.get("aggressiveness", 1),
            min_speech_ms=data.get("min_speech_ms", 200),
            max_silence_ms=data.get("max_silence_ms", 600),
        )


@dataclass
class FileOutputConfig:
    enabled: bool = False
    path: Path = Path("~/transcripts.txt")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileOutputConfig:
        return cls(
            enabled=data.get("enabled", False),
            path=Path(data.get("path", "~/transcripts.txt")),
        )


@dataclass
class OutputConfig:
    clipboard: bool = True
    file: FileOutputConfig = field(default_factory=FileOutputConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutputConfig:
        return cls(
            clipboard=data.get("clipboard", True),
            file=FileOutputConfig.from_dict(data.get("file", {})),
        )


@dataclass
class UiConfig:
    theme: str = "dark"
    welcome_shown: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UiConfig:
        theme = str(data.get("theme", "dark")).strip() or "dark"
        return cls(
            theme=theme,
            welcome_shown=bool(data.get("welcome_shown", False)),
        )


@dataclass
class HistoryConfig:
    max_entries: int = 5000

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryConfig:
        raw_value = data.get("max_entries", 5000)
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            parsed = 5000
        return cls(max_entries=max(1, parsed))


@dataclass
class AppConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    auto_copy: bool = True
    auto_paste: bool = True
    auto_revert_clipboard: bool = True

    def to_dict(self) -> dict[str, Any]:
        """
        Produce a dictionary representation of the AppConfig with file paths and model fields normalized for serialization.

        Returns:
            dict: Configuration data where output.file.path is a string and model.runtime, model.path, and model.language reflect the AppConfig's current values.
        """
        data = asdict(self)
        data["output"]["file"]["path"] = str(self.output.file.path)
        data["model"]["runtime"] = self.model.runtime
        data["model"]["path"] = self.model.path
        data["model"]["language"] = self.model.language
        return data


SUPPORTED_RUNTIMES = ("faster-whisper", "whisper.cpp")


def normalize_runtime_name(name: str) -> str:
    """
    Normalize a runtime identifier to a canonical runtime name.

    Returns:
        The canonical runtime name: returns the matching value from SUPPORTED_RUNTIMES when provided, `'whisper.cpp'` for the inputs `'whispercpp'`, `'whisper_cpp'`, or `'whisper-cpp'`, and `'faster-whisper'` for any unknown input.
    """
    normalized = (name or "").strip().lower()
    if normalized in SUPPORTED_RUNTIMES:
        return normalized
    if normalized in {"whispercpp", "whisper_cpp", "whisper-cpp"}:
        return "whisper.cpp"
    logger.warning("Unknown runtime '%s', falling back to 'faster-whisper'", name)
    return "faster-whisper"


def default_config_path() -> Path:
    return Path("~/.config/whisper.local/config.toml").expanduser()


def _load_default_config() -> dict[str, Any]:
    with resources.files("whisper_local").joinpath("default_config.toml").open("rb") as handle:
        return tomllib.load(handle)


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | None = None) -> AppConfig:
    """
    Load application configuration by merging built-in defaults with an optional user TOML file.

    Parameters:
        path (Path | None): Optional path to a TOML configuration file. If None, the default config path is used. If the file does not exist, only built-in defaults are used.

    Returns:
        AppConfig: The merged application configuration. The returned object has user values overriding defaults where provided, and file paths (model.path and output.file.path) expanded to user paths.
    """
    default_data = _load_default_config()
    config_path = path or default_config_path()
    if config_path.exists():
        with config_path.open("rb") as handle:
            user_data = tomllib.load(handle)
        merged = _deep_merge(default_data, user_data)
    else:
        merged = default_data

    config = AppConfig(
        model=ModelConfig.from_dict(merged.get("model", {})),
        hotkey=HotkeyConfig.from_dict(merged.get("hotkey", {})),
        audio=AudioConfig.from_dict(merged.get("audio", {})),
        vad=VadConfig.from_dict(merged.get("vad", {})),
        output=OutputConfig.from_dict(merged.get("output", {})),
        ui=UiConfig.from_dict(merged.get("ui", {})),
        history=HistoryConfig.from_dict(merged.get("history", {})),
        auto_copy=bool(merged.get("auto_copy", True)),
        auto_paste=bool(merged.get("auto_paste", True)),
        auto_revert_clipboard=bool(merged.get("auto_revert_clipboard", True)),
    )

    if config.model.path:
        config.model.path = str(Path(config.model.path).expanduser())
    config.output.file.path = config.output.file.path.expanduser()
    return config


def save_config(config: AppConfig, path: Path | None = None) -> None:
    def _strip_none(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _strip_none(v) for k, v in value.items() if v is not None}
        if isinstance(value, list):
            return [_strip_none(v) for v in value if v is not None]
        return value

    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = _strip_none(config.to_dict())
    data["output"]["file"]["path"] = str(config.output.file.path)
    with config_path.open("wb") as handle:
        tomli_w.dump(data, handle)
