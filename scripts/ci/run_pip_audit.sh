#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python}"
IGNORE_FILE="${1:-configs/security/pip-audit-ignore.txt}"

declare -a ignore_args
ignore_args=()

if [[ -f "${IGNORE_FILE}" ]]; then
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%%#*}"
    line="$(printf '%s' "${line}" | xargs)"
    if [[ -n "${line}" ]]; then
      ignore_args+=(--ignore-vuln "${line}")
    fi
  done < "${IGNORE_FILE}"
fi

"${PYTHON_BIN}" -m pip_audit --strict "${ignore_args[@]}"
