# whisper.local

Local, real-time voice transcription with a Textual TUI, backed by Whisper via faster-whisper. Runs fully offline on macOS.

## Features
- Global hotkey (PTT or toggle) for recording
- Local transcription with faster-whisper
- Textual TUI with transcript history and copy actions
- Optional clipboard and file output
- Optional RNNoise noise suppression (soft dependency)
- Model management (list/pull/remove/set default)

## Install (pip)
```bash
python -m pip install whisper-local
```

## RNNoise (optional, recommended)
```bash
brew install --cask rnnoise
```
If RNNoise is not found, the app will continue without noise suppression.

## Run
```bash
whisper-local
```

## macOS permissions
Global hotkeys require Input Monitoring permission for your terminal or app host.

## Hotkey
Default hotkey is `cmd+shift+space`. Configure it in the config file:
`~/.config/whisper-local/config.toml`
Supported keys: letters, digits, space, return, tab, escape.

## Model downloading
Models download automatically on first run. You can prefetch models:
```bash
whisper-local models pull small
```

## Configuration
Defaults live in `configs/default.toml`. The app reads overrides from:
`~/.config/whisper-local/config.toml`

## TUI key bindings
- `c`: copy latest transcript
- `enter`: copy selected transcript
- `y`: toggle auto-copy
- `n`: toggle noise suppression
- `v`: toggle VAD
- `m`: model manager
- `s`: show config path
- `q`: quit

## Homebrew (custom tap)
Planned for first release. The formula will install from wheels and provide a soft RNNoise hint.
