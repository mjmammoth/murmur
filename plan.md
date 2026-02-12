# whisper.local Next Steps Plan

This plan focuses on fixing first-run UX, tightening reliability, and preparing for Homebrew distribution.

## 1) First-run model download feedback (highest priority)

- [ ] Show immediate startup state in the TUI before model load begins (`Initializing...`).
- [ ] Detect whether the default model is already installed before creating `WhisperModel`.
- [ ] If missing, switch status to a clear download message:
  - `Model small not found locally. Downloading (first run)...`
- [ ] Add a visible spinner/progress indicator widget in the TUI while model load/download is in progress.
- [ ] Surface download progress if available from backend callbacks/logs; if exact progress is not available, show elapsed time and reassuring text (`This can take a few minutes on first run`).
- [ ] Keep the app responsive during download (all heavy work in worker thread, no blocking calls on UI thread).
- [ ] Add a post-download success message (`Model ready`) and transition to `Ready` state.
- [ ] Add explicit error handling for interrupted download/network failures with retry guidance.

## 2) Startup and runtime UX improvements

- [ ] Add a startup checklist section in status/footer:
  - Input Monitoring permission state
  - RNNoise availability
  - Current model/device
- [ ] Improve status text consistency with discrete states:
  - `Initializing`, `Downloading model`, `Loading model`, `Ready`, `Recording`, `Transcribing`, `Error`.
- [ ] Add a short in-app help modal (`?`) showing key bindings and troubleshooting tips.

## 3) Model management hardening

- [ ] Expand Model Manager to show:
  - Installed model size (if known)
  - Cache path
  - Active/default model
- [ ] Add explicit `Pull` progress and non-blocking UI updates.
- [ ] Add safe remove confirmation for installed models.

## 4) Config and settings maintainability

- [ ] Build a proper TUI settings screen (not just “edit config path”):
  - Hotkey mode/key
  - Output clipboard/file + path
  - Noise suppression toggle
  - VAD toggle + aggressiveness
- [ ] Validate and persist settings changes immediately.
- [ ] Add schema-style validation for config values on load.

## 5) Reliability and tests

- [ ] Add unit tests for config parsing/merge/defaults.
- [ ] Add tests for model install detection and startup state transitions.
- [ ] Add smoke test for CLI commands (`models list`, `config`).
- [ ] Add type checking and linting in CI.

## 6) Packaging and Homebrew readiness

- [ ] Build universal/arch-specific wheels in CI and attach to releases.
- [ ] Create custom tap repo with `Formula/whisper-local.rb`.
- [ ] Install from wheel in formula using `python -m venv` + `pip`.
- [ ] Add `caveats` in formula for optional RNNoise cask install.
- [ ] Document upgrade path and known limitations in README.

## 7) Documentation updates

- [ ] Add a “First run behavior” section in README (model download expectations).
- [ ] Add troubleshooting section for:
  - Long first startup
  - Missing permissions
  - Missing RNNoise
  - No transcription output
- [ ] Add architecture notes for future contributors.

## Suggested implementation order

1. First-run model download feedback + non-blocking startup.
2. Runtime status/state cleanup.
3. Settings UI and config validation.
4. Tests and CI quality gates.
5. Homebrew tap + release automation polish.
