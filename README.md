# whisper.local

Local, real-time voice transcription with a Textual TUI, backed by Whisper. Runs fully offline on macOS.

## Features
- Global hotkey (PTT or toggle) for recording
- macOS menu bar status dot (idle/recording/transcribing/success pulse)
- Local transcription with pluggable backends (`faster-whisper` or `whisper.cpp`)
- Textual TUI with transcript history and copy actions
- Drag-and-drop/paste audio file paths into the TUI to transcribe local files
- Optional clipboard and file output
- Optional RNNoise noise suppression (soft dependency)
- Model management (list/pull/remove/select)

## Install (pip)
```bash
python -m pip install whisper-local
```

## Required system dependency: whisper.cpp
```bash
brew install whisper-cpp
```
`whisper.local` requires a `whisper.cpp` binary at runtime. The app fails fast with an actionable message if it is missing.
Then choose backend in Settings -> Model -> Backend.

## RNNoise (optional, recommended)
```bash
brew install --cask rnnoise
```
For Python runtime integration, also install:
```bash
python -m pip install "whisper-local[rnnoise]"
```
The Homebrew cask provides Audio Unit/VST plugins; those are not always directly loadable via ctypes.
If RNNoise still is not available, the app continues without noise suppression.

## Run
```bash
whisper.local
```
`whisper-local` also works as an alias.
Use `whisper.local run --no-status-indicator` to disable the macOS menu bar indicator.

## macOS permissions
Global hotkeys require Input Monitoring permission for your terminal or app host.

## Hotkey
Default hotkey is `f3`. Configure it in the config file:
`~/.config/whisper.local/config.toml`
Supported keys: letters, digits, space, return, tab, escape, and function keys `f1`-`f12`.

## Model downloading
Models download automatically on first run. You can prefetch models:
```bash
whisper.local models pull small
whisper.local models select small
```

## Runtime device
- `faster-whisper`: CPU/CUDA (mps falls back to CPU)
- `whisper.cpp`: CPU + Metal (`mps`) when available

Unavailable backend/device options are shown disabled with an inline reason in Settings.

## Benchmark logging
Logs include per-job benchmark details (backend, model size, input audio length, RNNoise/VAD states,
transcribe time, total pipeline time, and realtime factor) so you can compare backend performance.

## Configuration
Defaults live in `configs/default.toml`. The app reads overrides from:
`~/.config/whisper.local/config.toml`

## TUI key bindings
- `c`: copy latest transcript
- `enter`: copy selected transcript
- `a`: toggle auto-copy
- `n`: toggle noise suppression
- `v`: toggle VAD
- `o`: toggle hotkey mode (ptt/toggle)
- `h`: hotkey modal
- `m`: model manager
- `s`: interactive settings menu
- drag/drop (paste path): transcribe audio file(s)
- `q`: quit

## Homebrew (custom tap)
Planned for first release. The formula will install from wheels and provide a soft RNNoise hint.

Packaging note for optional dependencies:
- Python optional extras (e.g. `whisper-local[rnnoise]`) are **not** auto-installed unless requested.
- Homebrew formula dependencies are installed by brew; for this project, `whisper-cpp` should be a required
  formula dependency (hard dependency).
