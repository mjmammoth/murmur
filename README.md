# whisper.local

**Press a key. Speak. Text appears in your app.** Local, private voice transcription — nothing leaves your machine.

<!-- tui-showcase:start -->
![whisper.local TUI home across themes](docs/assets/tui-home-themes.png)
<!-- tui-showcase:end -->

## How it works

1. **Hit F3** (or your custom hotkey) from any app — system-wide, no focus switching
2. **Speak** — audio is captured, noise-suppressed, and transcribed locally by Whisper
3. **Text appears** — transcription auto-pastes into your active app, or copies to clipboard

Everything runs on your machine. No cloud API, no network calls, no data collection. Your voice stays on your machine, always.

> [!IMPORTANT]
> This repo is 99.9999999% vibe-coded.
> Literally only this disclaimer is human-written.

## Features

- **100% local & private** — no cloud, no telemetry, no network calls
- **Global hotkey** (push-to-talk or toggle) — works system-wide from any app
- **Auto-copy** — transcription goes straight to clipboard
- **Auto-paste** — transcribed text pastes directly into your active application
- **Auto-revert clipboard** — after auto-paste, previous clipboard content is restored by default
- **Terminal UI** built with OpenTUI + SolidJS — configure settings, transcript history
- **Pluggable runtimes** — faster-whisper (CPU/CUDA) or whisper.cpp (CPU/Metal GPU on macOS)
- **Model management** — download, remove, and select OpenAI Whisper models from tiny to large-v3-turbo
- **macOS menu bar indicator** — status dot shows recording / transcribing / idle state
- Optional **Noise suppression** (RNNoise) and **voice activity detection** (VAD)
- **File transcription** — drag-and-drop or paste audio file paths

## Get Started

### Install via `curl | bash` (macOS + Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/mjmammoth/whisper.local/main/install | bash
```

Installer verification and overrides:
- By default, the installer verifies release checksums and GPG signatures before install/extract.
- Disable verification only when necessary:

```bash
curl -fsSL https://raw.githubusercontent.com/mjmammoth/whisper.local/main/install | bash -s -- --no-verify
curl -fsSL https://raw.githubusercontent.com/mjmammoth/whisper.local/main/install | NO_VERIFY=true bash
curl -fsSL https://raw.githubusercontent.com/mjmammoth/whisper.local/main/install | WHISPER_LOCAL_NO_VERIFY=1 bash
```

- Override signing verification inputs when needed:
  - `WHISPER_LOCAL_SIGNING_KEY_FINGERPRINT` (defaults to release signing fingerprint)
  - `WHISPER_LOCAL_SIGNING_KEY_URL` (defaults to `https://github.com/<repo-owner>.gpg`)
- Override runtime launcher paths if your install layout is custom:
  - `WHISPER_LOCAL_HOME`
  - `WHISPER_VENV_DIR`
  - `WHISPER_LOCAL_TUI_BIN`

### Homebrew (macOS Intel/Apple Silicon + Linux x64/arm64)

```bash
brew tap mjmammoth/tap
brew install whisper-local
```

### RNNoise (optional)

```bash
brew install --cask rnnoise
```

### Service-first commands

```bash
whisper.local                 # start/ensure background service
whisper.local service status  # check service state
whisper.local tui             # attach TUI to running service
whisper.local trigger toggle  # hotkey fallback trigger command
whisper.local trigger start --timeout-seconds 5
whisper.local upgrade         # upgrade installer-managed install to latest
whisper.local --version       # print installed version
whisper.local version         # subcommand alias
whisper.local service stop    # stop background service
```

### Hotkey

Default hotkey is `f3`. Configure it through the TUI (by pressing 'h') or in the config file:
`~/.config/whisper.local/config.toml`
Supported keys: letters, digits, space, return, tab, escape, and function keys `f1`-`f12`.
Transcript history retention is configured with `[history] max_entries` (default `5000`).

### macOS permissions

Global hotkeys require **Input Monitoring** permission for your terminal or app host.
Auto-paste uses System Events and requires the **Accessibility** permission for the terminal or app running whisper.local.

### Wayland guidance

Global key swallow is not guaranteed on Wayland. Use a desktop shortcut that runs:

```bash
whisper.local trigger toggle
```

### Native hotkey support

- macOS: native capture + swallow
- Linux X11: native capture + swallow (best-effort), requires `python-xlib`
- Linux Wayland: no guaranteed swallow; use `whisper.local trigger toggle` fallback
- Windows: native capture + swallow (best-effort), requires `pywin32`

### Windows

Windows builds are published as release artifacts (`whisper-local-tui-windows-x64.tar.gz`) with a documented manual install path.

### Upgrade

Installer-managed installs support in-place upgrades:

```bash
whisper.local upgrade
whisper.local upgrade --version v0.2.0
```

Behavior:
- If the background service is running, upgrade stops it and restarts it automatically on success.
- Homebrew installs receive: `brew update && brew upgrade whisper-local`.
- pip installs receive: `python -m pip install -U whisper-local`.

### Troubleshooting hotkey deps

If Linux X11 hotkey support is unavailable:

```bash
python -m pip install python-xlib
```

If Windows hotkey support is unavailable:

```bash
python -m pip install pywin32
```


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
