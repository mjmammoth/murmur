# Release Flow

This project uses canonical PEP 440 versioning with a required `v` tag prefix for Git tags.
Examples: `v1.2.3`, `v1.2.3.post1`, `v1.2.4rc1`, `v1.2.4.dev1`.

## Release Flow Diagram

```mermaid
flowchart TD
  A["Push tag (vX.Y.Z...)"] --> B{"Classify tag"}
  B -->|stable| C["GitHub Release prerelease=false"]
  B -->|post| D["GitHub Release prerelease=false"]
  B -->|prerelease (a/b/rc/dev)| E["GitHub Release prerelease=true"]

  C --> F["Update Homebrew formula whisper-local"]
  D --> F
  E --> G["Update Homebrew formula whisper-local-preview"]

  C --> H["Default install/upgrade latest -> stable"]
  D --> H
  E --> I["Install prerelease only by explicit tag"]
```

## Tag Policy

Use canonical PEP 440 with a leading `v`:

- Stable: `vX.Y.Z`
- Post release: `vX.Y.Z.postN`
- Pre-release: `vX.Y.ZaN`, `vX.Y.ZbN`, `vX.Y.ZrcN`, `vX.Y.Z.devN`

Rejected examples:

- `v1.2`
- `v1.2.3-rc1`
- `v1.2.3+build1`
- `1.2.3` (missing `v` prefix)

## Choosing `rc` vs `post`

- Use `rc` (or `a`, `b`, `dev`) when validating a version before final stable release.
- Use `.postN` when republishing a stable series without changing base version semantics, for example release metadata/packaging fixes.
- Use a patch bump (`X.Y.(Z+1)`) for normal code changes intended as a new stable line.

## GitHub Release Behavior

- Stable and post tags publish as full releases (`prerelease=false`).
- Pre-release tags publish as prereleases (`prerelease=true`).
- `releases/latest` tracks the latest non-prerelease, non-draft release.

## Homebrew Channels

- Stable + post tags update `Formula/whisper-local.rb`.
- Pre-release tags update `Formula/whisper-local-preview.rb`.
- Preview formula conflicts with stable formula because both install the same executables.

Install commands:

```bash
brew tap mjmammoth/tap
brew install whisper-local
brew install whisper-local-preview
```

## Installer and Upgrade Defaults

- Installer default (`install` with no tag) resolves GitHub `releases/latest`, so it stays on stable/post releases.
- CLI upgrade default (`whisper.local upgrade`) uses the same latest stable behavior.
- To install a prerelease explicitly, pass the tag:

```bash
curl -fsSL https://raw.githubusercontent.com/mjmammoth/whisper.local/main/install | bash -s -- v1.2.4rc1
whisper.local upgrade --version v1.2.4rc1
```

## Release Checklist

1. Ensure CI is green on `main`.
2. Choose a canonical tag according to this policy.
3. Create and push the tag, for example:
   `git tag v1.2.4rc1 && git push origin v1.2.4rc1`
4. Wait for `.github/workflows/release.yml` to complete.
5. Verify GitHub release type (`prerelease` flag) matches tag intent.
6. Verify the expected Homebrew formula file was updated in tap.
