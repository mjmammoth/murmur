from __future__ import annotations

from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import tomllib
import tomli_w


@dataclass
class ModelConfig:
    name: str = "small"
    backend: str = "faster-whisper"
    device: str = "cpu"
    compute_type: str = "int8"
    auto_download: bool = True
    path: str | None = None
    language: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelConfig:
        return cls(
            name=data.get("name", "small"),
            backend=normalize_backend_name(str(data.get("backend", "faster-whisper"))),
            device=data.get("device", "cpu"),
            compute_type=data.get("compute_type", "int8"),
            auto_download=data.get("auto_download", True),
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
    noise_suppression: NoiseSuppressionConfig = field(default_factory=NoiseSuppressionConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioConfig:
        return cls(
            sample_rate=data.get("sample_rate", 48000),
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UiConfig:
        theme = str(data.get("theme", "dark")).strip() or "dark"
        return cls(theme=theme)


@dataclass
class AppConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    auto_copy: bool = False
    auto_paste: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["output"]["file"]["path"] = str(self.output.file.path)
        data["model"]["backend"] = self.model.backend
        data["model"]["path"] = self.model.path
        data["model"]["language"] = self.model.language
        return data


SUPPORTED_BACKENDS = ("faster-whisper", "whisper.cpp")


def normalize_backend_name(name: str) -> str:
    """Normalize a backend name to a canonical form."""
    normalized = (name or "").strip().lower()
    if normalized in SUPPORTED_BACKENDS:
        return normalized
    if normalized in {"whispercpp", "whisper_cpp", "whisper-cpp"}:
        return "whisper.cpp"
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
        auto_copy=bool(merged.get("auto_copy", False)),
        auto_paste=bool(merged.get("auto_paste", False)),
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
