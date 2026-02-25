from whisper_local.platform.capabilities import PlatformCapabilities
from whisper_local.platform.factory import (
    create_hotkey_provider,
    create_paste_provider,
    create_status_indicator_provider,
    detect_platform_capabilities,
    parse_hotkey_tokens,
    validate_hotkey,
)
from whisper_local.platform.providers import (
    DefaultPasteProvider,
    HotkeyProvider,
    MacOSHotkeyProvider,
    NoopPasteProvider,
    NoopHotkeyProvider,
    NoopStatusIndicatorProvider,
    PasteProvider,
    StatusIndicatorProvider,
    SubprocessStatusIndicatorProvider,
    WindowsHotkeyProvider,
    X11HotkeyProvider,
)

__all__ = [
    "DefaultPasteProvider",
    "HotkeyProvider",
    "MacOSHotkeyProvider",
    "NoopPasteProvider",
    "NoopHotkeyProvider",
    "NoopStatusIndicatorProvider",
    "PasteProvider",
    "PlatformCapabilities",
    "StatusIndicatorProvider",
    "SubprocessStatusIndicatorProvider",
    "WindowsHotkeyProvider",
    "X11HotkeyProvider",
    "create_hotkey_provider",
    "create_paste_provider",
    "create_status_indicator_provider",
    "detect_platform_capabilities",
    "parse_hotkey_tokens",
    "validate_hotkey",
]
