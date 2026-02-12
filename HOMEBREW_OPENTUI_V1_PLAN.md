# Homebrew OpenTUI Packaging Plan (v1, macOS-only)

## Goal

Ship `whisper-local` as a single Homebrew tap formula with:

- Python backend runtime (bridge/transcription/hotkey/model management)
- Prebuilt OpenTUI binary (no Bun required at install or runtime)

v1 scope is **macOS only** (Apple Silicon + Intel), and supports **only the new OpenTUI path** (no legacy Textual path in formula behavior/docs).

## Non-Goals (v1)

- Linux packaging support
- Bun-based runtime fallback in Homebrew installs
- Legacy Textual TUI in Homebrew distribution path

---

## Architecture Decision

Use a hybrid install in one formula:

1. Install Python package into `libexec` virtualenv via Homebrew Python helpers.
2. Install prebuilt OpenTUI binary asset for the current macOS CPU.
3. Provide one executable `whisper-local` that launches Python backend + packaged TUI binary.

This keeps end-user install one-command and Bun-free.

---

## Workstreams

## 1) CLI Runtime Resolution (OpenTUI-only packaged path)

### Changes

- Update `src/whisper_local/cli.py` to resolve TUI executable in this order:
  1. Explicit env override (debug/dev only)
  2. Packaged install path (Homebrew-managed binary location)
  3. Local dev fallback (repo `tui` + Bun) for contributors only
- Ensure default `whisper-local run` uses packaged binary when installed.
- Ensure Homebrew installs are deterministic:
  - If packaged binary is missing, fail with an actionable message.
  - Do not route Homebrew users into Bun instructions.

### Acceptance

- On macOS with Homebrew install and no Bun, `whisper-local run` launches TUI successfully.
- Errors are explicit if binary cannot be found/executed.

---

## 2) Build OpenTUI Binaries for macOS

### Changes

- Add deterministic TUI build script (for example `tui/scripts/build.ts`) using Bun compile/build flow.
- Produce per-arch artifacts:
  - `whisper-local-tui-darwin-arm64.tar.gz`
  - `whisper-local-tui-darwin-x64.tar.gz`
- Artifact contents:
  - single executable `whisper-local-tui`
  - optional metadata/version file
- Ensure executable bit and reproducible archive structure.

### Acceptance

- Both archives run on their target architecture without Bun installed.
- Binary starts and connects to backend bridge.

---

## 3) GitHub Release Pipeline

### Changes

- Extend CI release workflow to produce:
  - Python distributions (`sdist`, `wheel`)
  - OpenTUI macOS binaries (arm64 + x64)
  - SHA256 checksums for each release asset
- Upload all assets to GitHub Release on tag publish.
- Keep CI artifact upload for debugging.

### Acceptance

- A tagged release contains all required assets + checksums.
- Checksums are stable and usable in formula.

---

## 4) Homebrew Tap Formula (single formula)

### Tap Repo

- Create/use dedicated tap repo: `homebrew-tap`
- Formula file: `whisper-local.rb`

### Formula Behavior

- `depends_on "python@3.12"` (or chosen supported version)
- Add required runtime deps for audio stack as validated (likely `portaudio`)
- Install Python backend into venv in `libexec`
- Select/install correct TUI archive by CPU:
  - `on_macos` + `Hardware::CPU.arm?` / `Hardware::CPU.intel?`
- Place TUI executable under `libexec/"bin"` (or `pkgshare`)
- Install wrapper `bin/whisper-local` that invokes Python entrypoint with packaged TUI path available

### Acceptance

- `brew install <org>/tap/whisper-local` succeeds on Apple Silicon and Intel.
- `whisper-local --help` and `whisper-local run` work with no Bun.

---

## 5) Automated Formula Updates on Release

### Changes

- Add release publish script to:
  - read version + release asset SHAs
  - render `whisper-local.rb` template
  - commit/push formula update to tap repo
- Configure CI secret token with write access to tap repo.

### Acceptance

- New tag automatically updates tap formula to latest assets.
- No manual formula editing required for normal releases.

---

## 6) Validation Matrix (macOS-only v1)

### Automated checks

- `brew tap <org>/tap`
- `brew install whisper-local`
- `whisper-local --help`
- `whisper-local run --help` (or non-interactive smoke invocation)

### Manual smoke checks (release checklist)

- Launch TUI and confirm bridge connectivity.
- Confirm microphone/hotkey permission prompts documented.
- Verify model download path works from installed build.

### Acceptance

- Both Intel and ARM smoke checks pass before announcing release.

---

## 7) Documentation Updates

### README

- Add Homebrew tap install section:
  - `brew install <org>/tap/whisper-local`
- State macOS-only in v1.
- Explicitly state Bun is not required for Homebrew installs.

### Troubleshooting

- Input Monitoring / microphone permissions
- First-model-download timing
- Error messages for missing packaged TUI binary

### Acceptance

- Fresh users can install and run from README alone.

---

## Implementation Order

1. CLI packaged-binary resolution logic
2. OpenTUI binary build script + local validation
3. CI release workflow for assets + checksums
4. Tap formula creation and local `brew install` validation
5. Formula auto-update release automation
6. Documentation and release checklist finalization

---

## Risks and Mitigations

- **Arch-specific binary mismatch**
  - Mitigation: explicit CPU conditionals and separate SHA per asset.
- **Python audio dependency issues on user machines**
  - Mitigation: formula-level dependencies and smoke tests on clean macOS runners.
- **Release drift (formula points to wrong assets)**
  - Mitigation: generate formula from release outputs in one pipeline.
- **Runtime path brittleness**
  - Mitigation: single canonical packaged binary path + robust fallback/error handling.

---

## Definition of Done (v1)

- One-command install from tap on macOS Intel/ARM.
- OpenTUI launches without Bun.
- Python backend and model workflow operate normally.
- Formula updates automated from release tags.
- Docs reflect OpenTUI-only Homebrew path.
