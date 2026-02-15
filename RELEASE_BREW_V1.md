# Brew V1 Release Runbook

## Scope

- macOS arm64 only
- No Bun runtime dependency for end users
- Release artifacts include Python distributions plus prebuilt `whisper-local-tui` binary tarball

## Preconditions

- `HOMEBREW_TAP_TOKEN` secret is configured with push access to the tap repo
- Optional repo variable `HOMEBREW_TAP_REPO` is set (defaults to `<owner>/homebrew-tap` if omitted)
- Tap repository already contains `Formula/` directory

## Tagging Rules

- Use semantic tags in the form `vX.Y.Z`
- Push tag to trigger the release workflow:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Expected Release Assets

Each tagged release should contain:

- `whisper_local-<version>-py3-none-any.whl`
- `whisper-local-<version>.tar.gz` (sdist)
- `whisper-local-tui-darwin-arm64.tar.gz`
- `manifest.json` (TUI build metadata)
- `checksums.txt`

## Tap Update Verification

After the workflow completes:

1. Confirm tap repo has commit `whisper-local <version>`
2. Confirm `Formula/whisper-local.rb` points to:
   - wheel URL for the matching release tag
   - TUI tarball URL for the matching release tag
   - matching SHA256 values from `checksums.txt`
3. Validate install on clean arm64 macOS:

```bash
brew tap <org>/tap
brew install whisper-local
whisper-local --help
whisper-local bridge --help
```

## Rollback

If release assets or formula are bad:

1. Revert the formula commit in the tap repo to the last known good version.
2. Push the revert commit.
3. If needed, delete or mark the GitHub release as pre-release while fixing.
4. Publish a new patch release tag `vX.Y.(Z+1)` with corrected assets.
