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

## TUI showcase refresh

When a change affects the TUI home screenshot, regenerate the showcase before opening a PR.

```bash
python -m pip install --requirement scripts/requirements-tui-showcase.txt
bun install --frozen-lockfile --cwd tui
npm ci
npx playwright install chromium --with-deps
python scripts/generate_tui_showcase.py --output-format png --png-scale 2
```

This command updates:

- `README.md`
- `docs/assets/tui-home-themes.png`

## Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

## Quality checks

Run these before opening a pull request:

```bash
pytest
ruff check src/
mypy src/
```

## Branch and pull request workflow

- Create a feature branch from `main`
- Keep PRs focused and scoped to one change
- Link the related issue when available
- Include test updates and docs updates when behavior changes

## Release process

Release channel/tag policy and flow are documented in [`docs/release-flow.md`](docs/release-flow.md).
