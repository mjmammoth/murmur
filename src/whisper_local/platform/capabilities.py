from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PlatformCapabilities:
    hotkey_capture: bool
    hotkey_swallow: bool
    status_indicator: bool
    auto_paste: bool
    hotkey_guidance: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
