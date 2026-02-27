# Contributing to whisper.local

Thanks for helping improve whisper.local.

## Development environment

Current development is macOS-only.

Prerequisites:

- macOS
- Python 3.12+
- Bun

Setup:

```bash
git clone https://github.com/mjmammoth/whisper.local.git
cd whisper.local
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## TUI development

The TUI can be developed with Bun-powered tooling.

```bash
cd tui
bun install
```

When running whisper.local for local UI development, set:

```bash
WHISPER_LOCAL_DEV_USE_BUN=1
```

## Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

## Quality checks

Run these before opening a pull request:

```bash
pre-commit run --all-files
pytest
ruff check src/
mypy src/
cd tui && bun test --timeout 5000
```

## Security scan exceptions

Security scans fail by default. Reviewed exceptions must be explicit and documented:

- Gitleaks allowlists: `.gitleaks.toml`
- pip-audit vulnerability ignores: `configs/security/pip-audit-ignore.txt`

## SonarCloud quality gate

- SonarCloud analysis and quality gate are required for pushes to `main` and same-repo PRs.
- Fork PRs skip SonarCloud because repository secrets are unavailable.

## Branch and pull request workflow

- Create a feature branch from `main`
- Keep PRs focused and scoped to one change
- Link the related issue when available
- Include test updates and docs updates when behavior changes

## Release process

Release channel/tag policy and flow are documented in [`docs/release-flow.md`](docs/release-flow.md).
