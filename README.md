# whisper.local

**Press a key. Speak. Text appears in your app.** Local, private voice transcription — nothing leaves your machine.

> [!IMPORTANT]
> This repo is 99.9999999% vibe-coded.
> Literally only this disclaimer is human-written.

<!-- tui-showcase:start -->
![whisper.local TUI home across themes](docs/assets/tui-home-themes.png)
<!-- tui-showcase:end -->

## How it works

1. **Hit F3** (or your custom hotkey) from any app — system-wide, no focus switching
2. **Speak** — audio is captured, noise-suppressed, and transcribed locally by Whisper
3. **Text appears** — transcription auto-pastes into your active app, or copies to clipboard

Everything runs on your machine. No cloud API, no network calls, no data collection. Your voice stays on your machine, always.

## Features

- **100% local & private** — no cloud, no telemetry, no network calls
- **Global hotkey** (push-to-talk or toggle) — works system-wide from any app
- **Auto-copy** — transcription goes straight to clipboard
- **Auto-paste** — transcribed text pastes directly into your active application
- **Auto-revert clipboard** — after auto-paste, previous clipboard content is restored by default
- **Terminal UI** built with OpenTUI + SolidJS — transcript history, click-to-copy, theme picker
- **Pluggable runtimes** — faster-whisper (CPU/CUDA) or whisper.cpp (CPU/Metal GPU on macOS)
- **Model management** — download, remove, and select OpenAI Whisper models from tiny to large-v3-turbo
- **macOS menu bar indicator** — status dot shows recording / transcribing / idle state
- Optional **Noise suppression** (RNNoise) and **voice activity detection** (VAD)
- **File transcription** — drag-and-drop or paste audio file paths

## Get Started
### Homebrew (v1 arm64)

```bash
brew tap mjmammoth/tap
brew install whisper.local
```

### RNNoise (optional)

```bash
brew install --cask rnnoise
```

### Run

```bash
whisper.local
```

### Hotkey

Default hotkey is `f3`. Configure it through the TUI (by pressing 'h') or in the config file:
`~/.config/whisper.local/config.toml`
Supported keys: letters, digits, space, return, tab, escape, and function keys `f1`-`f12`.

### macOS permissions

Global hotkeys require **Input Monitoring** permission for your terminal or app host.
Auto-paste uses System Events and requires the **Accessibility** permission for the terminal or app running whisper.local.


### Model downloading

Model files are runtime-specific, and so changing runtimes necessitates downloading models again.
- `faster-whisper` uses CTranslate2 artifacts
- `whisper.cpp` uses `ggml-*.bin` artifacts

You can also prefetch from CLI:

```bash
whisper.local models pull small
whisper.local models pull small --runtime whisper.cpp
whisper.local models select small
```

## Runtime device

- `faster-whisper`: CPU/CUDA (mps falls back to CPU)
- `whisper.cpp`: CPU + Metal (`mps`) when available

## TUI key bindings
Key bindings are visualised in the TUI by highlighted letters in function words.

- `enter`: copy selected transcript
- `o`: toggle hotkey mode (ptt/toggle)
- `h`: hotkey modal
- `m`: model manager
- `s`: interactive settings menu
- `t`: theme picker
- drag/drop (paste path): transcribe audio file(s)
- `q`: quit
