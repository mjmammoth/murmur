# whisper.local

Local, real-time voice transcription with a Textual TUI frontend, backed by Whisper. Runs fully offline on macOS.

> [!IMPORTANT]
> This repo is 99.9999999% vibe-coded with Opus 4.6, codex-5.3-xhigh, using various harnesses.
> Literally only this notification is human written.

## Features

- Global hotkey (PTT or toggle) for recording
- macOS menu bar status dot (idle/recording/transcribing/success pulse)
- Local transcription with pluggable backends (`faster-whisper` or `whisper.cpp`)
- Textual TUI frontend with transcript history and copy actions
- Drag-and-drop/paste audio file paths into the TUI to transcribe local files
- Optional clipboard and file output
- Optional RNNoise noise suppression (soft dependency)
- Model management (list/pull/remove/select)

## Install (pip)

```bash
python -m pip install whisper-local
```

## Homebrew (v1 arm64)

```bash
brew tap mjmammoth/homebrew-tap
brew install whisper-local
```

Homebrew installs a prebuilt TUI binary plus Python backend. Bun is **not** required at runtime.

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
For local contributors running from source, set `WHISPER_LOCAL_DEV_USE_BUN=1` (Bun is a JavaScript/TypeScript runtime) to use Bun-backed TUI dev mode.

## macOS permissions

Global hotkeys require Input Monitoring permission for your terminal or app host.
Auto-paste uses System Events and requires Accessibility permission for the terminal or app running whisper.local. Grant permission in **System Settings → Privacy & Security → Accessibility** — add Terminal (or your Python/app launcher) to the allowed apps list. Without this permission, auto-paste will fail silently or report a permission error.

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
- `p`: toggle auto-paste
- `n`: toggle noise suppression
- `v`: toggle VAD
- `o`: toggle hotkey mode (ptt/toggle)
- `h`: hotkey modal
- `m`: model manager
- `s`: interactive settings menu
- `t`: theme picker
- drag/drop (paste path): transcribe audio file(s)
- `q`: quit

## Homebrew notes (Developer/Release operators — not for end users)

- Formula wrapper sets `WHISPER_LOCAL_TUI_BIN` to the packaged `whisper-local-tui` executable.
- Homebrew formula dependencies are installed by brew, including `whisper-cpp`.
- Python optional extras (for example `whisper-local[rnnoise]`) are not auto-installed unless requested.
- Optional RNNoise support remains best-effort because cask-provided plugins are not always directly loadable.
- Release operators should follow `RELEASE_BREW_V1.md`.
