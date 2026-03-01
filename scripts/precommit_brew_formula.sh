#!/usr/bin/env bash
# Pre-commit hook: render the Homebrew formula template with dummy values
# and run brew style + brew audit to catch syntax/style issues early.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
TAP_NAME="local/murmur-lint"

cleanup() {
  brew untap "$TAP_NAME" 2>/dev/null || true
  if [ -n "${TAP_DIR:-}" ] && [ -d "$TAP_DIR" ]; then
    rm -rf "$TAP_DIR"
  fi
}
trap cleanup EXIT

TAP_DIR="$(mktemp -d)"
mkdir -p "$TAP_DIR/Formula"

DUMMY_SHA="$(printf 'a%.0s' {1..64})"

"$PYTHON" "$REPO_ROOT/scripts/update_tap_formula.py" \
  --wheel-url "https://example.com/murmur-0.0.0-py3-none-any.whl" \
  --wheel-sha256 "$DUMMY_SHA" \
  --tui-url "https://example.com/murmur-tui-darwin-arm64.tar.gz" \
  --tui-sha256 "$DUMMY_SHA" \
  --repository "test/murmur" \
  --tap-repo-path "$TAP_DIR"

git -C "$TAP_DIR" init -q
git -C "$TAP_DIR" config user.name "lint"
git -C "$TAP_DIR" config user.email "lint@localhost"
git -C "$TAP_DIR" add -A && git -C "$TAP_DIR" commit -q -m "lint"

brew untap "$TAP_NAME" 2>/dev/null || true
brew tap "$TAP_NAME" "$TAP_DIR" 2>/dev/null

brew style --formula "$TAP_NAME/murmur"
brew audit --formula "$TAP_NAME/murmur"
