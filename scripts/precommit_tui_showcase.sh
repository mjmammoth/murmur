#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ "${WHISPER_LOCAL_SKIP_TUI_SHOWCASE:-0}" == "1" ]]; then
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[whisper.local] python3 is required for TUI showcase generation." >&2
  exit 1
fi

python3 scripts/generate_tui_showcase.py
git add README.md
if [[ -f docs/assets/tui-home-themes.svg ]] || git ls-files --error-unmatch docs/assets/tui-home-themes.svg >/dev/null 2>&1; then
  git add -A docs/assets/tui-home-themes.svg
fi
if [[ -f docs/assets/tui-home-themes.png ]] || git ls-files --error-unmatch docs/assets/tui-home-themes.png >/dev/null 2>&1; then
  git add -A docs/assets/tui-home-themes.png
fi
