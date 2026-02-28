# GitHub Actions Pinning Policy

This is the canonical policy for action pinning in this repository.

## Required format

All `uses:` references in `.github/workflows/*.yml` must:

- Pin to a full 40-character commit SHA.
- Include the matching stable version as an inline comment.
- Use spaced comment style: `# vX.Y.Z`.

Example:

```yaml
uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
```

## Approved action pins

| Repository                                | Stable tag | Commit SHA                               |
| ----------------------------------------- | ---------- | ---------------------------------------- |
| actions/checkout                          | v6.0.2     | de0fac2e4500dabe0009e67214ff5f5447ce83dd |
| actions/setup-python                      | v6.2.0     | a309ff8b426b58ec0e2a45f0f869d46889d02405 |
| actions/setup-node                        | v6.2.0     | 6044e13b5dc448c55e2357c09f80417699197238 |
| actions/upload-artifact                   | v7.0.0     | bbbca2ddaa5d8feaa63e36b76fdaad77386f024f |
| actions/download-artifact                 | v8.0.0     | 70fc10c6e5e1ce46ad2ea6f2b72d43f7d47b13c3 |
| actions/attest-build-provenance           | v4.1.0     | a2bbfa25375fe432b6a289bc6b6cd05ecd0c4c32 |
| anchore/sbom-action/download-syft         | v0.22.2    | 28d71544de8eaf1b958d335707167c5f783590ad |
| oven-sh/setup-bun                         | v2.1.2     | 3d267786b128fe76c2f16a390aa2448b815359f3 |
| peter-evans/create-pull-request           | v8.1.0     | c0f553fe549906ede9cf27b5156039d195d2ece0 |
| softprops/action-gh-release               | v2.5.0     | a06a81a03ee405af7f2048a818ed3f03bbf83c7b |
| SonarSource/sonarqube-scan-action         | v7.0.0     | a31c9398be7ace6bbfaf30c0bd5d415f843d45e9 |
| SonarSource/sonarqube-quality-gate-action | v1.2.0     | cf038b0e0cdecfa9e56c198bbb7d21d751d62c3b |
