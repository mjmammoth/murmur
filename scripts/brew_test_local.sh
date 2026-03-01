#!/usr/bin/env bash
# Test the Homebrew formula locally by building artifacts, rendering the formula
# with file:// URLs, and running brew style/audit/install/test against it.
#
# Usage:
#   ./scripts/brew_test_local.sh                # full: build + install + test
#   ./scripts/brew_test_local.sh --audit-only   # fast: build + style/audit only
#   ./scripts/brew_test_local.sh --skip-build   # skip building if dist/ exists
#   ./scripts/brew_test_local.sh --no-cleanup   # leave tap + formula for inspection

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAP_NAME="local/murmur-dev"
FORMULA_NAME="murmur"

# Prefer python3 (pyenv may not expose bare "python").
PYTHON="${PYTHON:-python3}"

SKIP_BUILD=false
NO_CLEANUP=false
AUDIT_ONLY=false
STRICT=false

for arg in "$@"; do
  case "$arg" in
    --skip-build)  SKIP_BUILD=true ;;
    --no-cleanup)  NO_CLEANUP=true ;;
    --audit-only)  AUDIT_ONLY=true ;;
    --strict)      STRICT=true ;;
    --help|-h)
      echo "Usage: $0 [--skip-build] [--no-cleanup] [--audit-only] [--strict]"
      echo ""
      echo "  --skip-build   Reuse existing artifacts in dist/"
      echo "  --no-cleanup   Leave the local tap and installed formula"
      echo "  --audit-only   Only run brew style + audit (no install)"
      echo "  --strict       Fail on brew style/audit errors"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

TAP_DIR=""

cleanup() {
  if [ "$NO_CLEANUP" = true ]; then
    echo "Skipping cleanup (--no-cleanup). Tap dir: ${TAP_DIR:-<none>}"
    return
  fi
  echo "Cleaning up..."
  # Only uninstall if it was installed from our dev tap (check the tap prefix).
  if brew list "$FORMULA_NAME" &>/dev/null; then
    INSTALLED_TAP="$(brew info --json=v2 "$FORMULA_NAME" 2>/dev/null | "$PYTHON" -c "
import sys, json
data = json.load(sys.stdin)
for f in data.get('formulae', []):
    tap = f.get('tap', '')
    if tap: print(tap)
" 2>/dev/null || true)"
    if [ "$INSTALLED_TAP" = "$TAP_NAME" ]; then
      brew uninstall "$FORMULA_NAME" 2>/dev/null || true
    else
      echo "  Skipping uninstall — $FORMULA_NAME is from tap '$INSTALLED_TAP', not '$TAP_NAME'"
    fi
  fi
  brew untap "$TAP_NAME" 2>/dev/null || true
  if [ -n "$TAP_DIR" ] && [ -d "$TAP_DIR" ]; then
    rm -rf "$TAP_DIR"
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 1. Build artifacts
# ---------------------------------------------------------------------------
if [ "$SKIP_BUILD" = false ]; then
  echo "==> Building Python wheel..."
  BUILD_VENV="$REPO_ROOT/.brew-test-venv"
  "$PYTHON" -m venv "$BUILD_VENV"
  "$BUILD_VENV/bin/python" -m pip install --upgrade pip build -q
  (cd "$REPO_ROOT" && "$BUILD_VENV/bin/python" -m build --wheel)
  rm -rf "$BUILD_VENV"

  echo "==> Building TUI binary..."
  (cd "$REPO_ROOT/tui" && bun install --frozen-lockfile && bun run build:release)
else
  echo "==> Skipping build (--skip-build)"
fi

# ---------------------------------------------------------------------------
# 2. Locate artifacts and compute checksums
# ---------------------------------------------------------------------------
WHEEL_PATH="$(find "$REPO_ROOT/dist" -maxdepth 1 -type f -name '*.whl' -print -quit 2>/dev/null)"
OS_RAW="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH_RAW="$(uname -m)"

case "$OS_RAW" in
  darwin|linux) OS="$OS_RAW" ;;
  *)
    echo "Error: Unsupported OS '$OS_RAW' for local TUI artifact lookup." >&2
    exit 1
    ;;
esac

case "$ARCH_RAW" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64|amd64) ARCH="amd64" ;;
  *)
    echo "Error: Unsupported architecture '$ARCH_RAW' for local TUI artifact lookup." >&2
    exit 1
    ;;
esac

TUI_PATH="$REPO_ROOT/dist/tui/murmur-tui-$OS-$ARCH.tar.gz"

if [ -z "$WHEEL_PATH" ] || [ ! -f "$WHEEL_PATH" ]; then
  echo "Error: No wheel found in dist/. Run without --skip-build." >&2
  exit 1
fi
if [ ! -f "$TUI_PATH" ]; then
  echo "Error: TUI tarball not found at $TUI_PATH. Run without --skip-build." >&2
  exit 1
fi

WHEEL_SHA="$(shasum -a 256 "$WHEEL_PATH" | awk '{print $1}')"
TUI_SHA="$(shasum -a 256 "$TUI_PATH" | awk '{print $1}')"
VERSION="$("$PYTHON" -c "
import tomllib, pathlib
data = tomllib.loads(pathlib.Path('$REPO_ROOT/pyproject.toml').read_text())
print(data['project']['version'])
")"

echo "  Wheel:   $WHEEL_PATH (sha256: $WHEEL_SHA)"
echo "  TUI:     $TUI_PATH (sha256: $TUI_SHA)"
echo "  Version: $VERSION"

# ---------------------------------------------------------------------------
# 3. Set up local tap and render formula with file:// URLs
# ---------------------------------------------------------------------------
TAP_DIR="$(mktemp -d)"
mkdir -p "$TAP_DIR/Formula"

# Initialise a git repo in the tap dir — brew tap requires it.
git -C "$TAP_DIR" init -q
git -C "$TAP_DIR" config user.name "local-test"
git -C "$TAP_DIR" config user.email "local-test@localhost"

"$PYTHON" "$REPO_ROOT/scripts/update_tap_formula.py" \
  --version "$VERSION" \
  --wheel-url "file://$WHEEL_PATH" \
  --wheel-sha256 "$WHEEL_SHA" \
  --tui-url "file://$TUI_PATH" \
  --tui-sha256 "$TUI_SHA" \
  --repository "local/murmur" \
  --tap-repo-path "$TAP_DIR"

git -C "$TAP_DIR" add -A
git -C "$TAP_DIR" commit -q -m "local test formula"

FORMULA_FILE="$TAP_DIR/Formula/$FORMULA_NAME.rb"
echo "==> Formula rendered at $FORMULA_FILE"

# Remove stale tap if present, then register the new one.
brew untap "$TAP_NAME" 2>/dev/null || true
brew tap "$TAP_NAME" "$TAP_DIR"

# ---------------------------------------------------------------------------
# 4. Validate
# ---------------------------------------------------------------------------
echo "==> Running brew style..."
if [ "$STRICT" = true ]; then
  brew style --formula "$TAP_NAME/$FORMULA_NAME"
else
  brew style --formula "$TAP_NAME/$FORMULA_NAME" || true
fi

echo "==> Running brew audit..."
if [ "$STRICT" = true ]; then
  brew audit --formula "$TAP_NAME/$FORMULA_NAME"
else
  brew audit --formula "$TAP_NAME/$FORMULA_NAME" || true
fi

if [ "$AUDIT_ONLY" = true ]; then
  echo "==> Done (--audit-only). Skipping install."
  exit 0
fi

# ---------------------------------------------------------------------------
# 5. Install and test
# ---------------------------------------------------------------------------
echo "==> Running brew install..."
brew install "$TAP_NAME/$FORMULA_NAME"

echo "==> Running brew test..."
brew test "$TAP_NAME/$FORMULA_NAME"

echo "==> Local brew install test passed."
