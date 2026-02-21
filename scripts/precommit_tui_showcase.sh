#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ "${WHISPER_LOCAL_SKIP_TUI_SHOWCASE:-0}" == "1" ]]; then
  exit 0
fi

if [[ "${TERM_PROGRAM:-}" != "ghostty" && -z "${TMUX:-}" ]]; then
  cat >&2 <<'MSG'
[whisper.local] TUI showcase pre-commit hook requires Ghostty for consistent rendering.
Run your commit from Ghostty (or tmux inside Ghostty), or bypass once with:
  WHISPER_LOCAL_SKIP_TUI_SHOWCASE=1 git commit ...
MSG
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[whisper.local] python3 is required for TUI showcase generation." >&2
  exit 1
fi

if ! python3 - <<'PY' >/dev/null 2>&1
import importlib.util
required = ("PIL", "Quartz")
missing = [name for name in required if importlib.util.find_spec(name) is None]
raise SystemExit(0 if not missing else 1)
PY
then
  cat >&2 <<'MSG'
[whisper.local] Missing screenshot dependencies.
Install with:
  python3 -m pip install pillow pyobjc-framework-Quartz
MSG
  exit 1
fi

python3 scripts/generate_tui_showcase.py --renderer ghostty
git add README.md
if [[ -f docs/assets/tui-home-themes.svg ]] || git ls-files --error-unmatch docs/assets/tui-home-themes.svg >/dev/null 2>&1; then
  git add -A docs/assets/tui-home-themes.svg
fi
if [[ -f docs/assets/tui-home-themes.png ]] || git ls-files --error-unmatch docs/assets/tui-home-themes.png >/dev/null 2>&1; then
  git add -A docs/assets/tui-home-themes.png
fi
