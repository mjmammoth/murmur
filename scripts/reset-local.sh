#!/usr/bin/env bash
set -euo pipefail

log() {
  printf "%s\n" "$*"
  return 0
}

assert_safe_path() {
  local path="$1"
  local resolved
  resolved="$(cd "$(dirname "$path")" 2>/dev/null && pwd)/$(basename "$path")" 2>/dev/null || resolved="$path"
  if [[ -z "$resolved" || "$resolved" == "/" || "$resolved" == "$HOME" ]]; then
    log "FATAL: refusing to delete unsafe path: $path"
    exit 1
  fi
  local depth
  depth="$(echo "$resolved" | tr '/' '\n' | grep -c .)"
  if [[ "$depth" -lt 4 ]]; then
    log "FATAL: refusing to delete shallow path (depth $depth): $resolved"
    exit 1
  fi
  return 0
}

remove_path() {
  local path="$1"
  assert_safe_path "$path"
  if [[ -e "$path" || -L "$path" ]]; then
    rm -rf -- "$path"
    log "removed: $path"
    return
  fi
  log "missing: $path"
  return 0
}

remove_glob_matches() {
  local pattern="$1"
  local found=0
  local path
  while IFS= read -r path; do
    found=1
    remove_path "$path"
  done < <(compgen -G "$pattern" || true)
  if [[ $found -eq 0 ]]; then
    log "missing (pattern): $pattern"
  fi
  return 0
}

stop_running_processes() {
  log "stopping service/processes..."

  if command -v murmur >/dev/null 2>&1; then
    murmur stop >/dev/null 2>&1 || true
  fi

  pkill -f "python.*-m murmur\\.cli bridge" >/dev/null 2>&1 || true
  pkill -f "murmur\\.cli bridge" >/dev/null 2>&1 || true
  pkill -f "/murmur bridge" >/dev/null 2>&1 || true
  pkill -f "murmur-tui" >/dev/null 2>&1 || true
  return 0
}

main() {
  local state_dir="${HOME}/.local/state/murmur"
  local config_dir="${HOME}/.config/murmur"
  local app_home="${MURMUR_HOME:-${HOME}/.local/share/murmur}"
  local launcher_path="${HOME}/.local/bin/murmur"

  local hf_cache_root=""
  if [[ -n "${HF_HOME:-}" ]]; then
    hf_cache_root="${HF_HOME}"
  elif [[ -n "${XDG_CACHE_HOME:-}" ]]; then
    hf_cache_root="${XDG_CACHE_HOME}/huggingface"
  else
    hf_cache_root="${HOME}/.cache/huggingface"
  fi
  local hf_hub_dir="${hf_cache_root}/hub"

  log "resetting local murmur state..."
  stop_running_processes

  remove_path "$state_dir"
  remove_path "$config_dir"
  remove_path "$app_home"
  remove_path "$launcher_path"

  remove_glob_matches "${hf_hub_dir}/models--Systran--faster-whisper-*"
  remove_glob_matches "${hf_hub_dir}/models--dropbox-dash--faster-whisper-large-v3-turbo*"
  remove_glob_matches "${hf_hub_dir}/models--ggerganov--whisper.cpp*"
  remove_glob_matches "${hf_hub_dir}/.locks/models--Systran--faster-whisper-*"
  remove_glob_matches "${hf_hub_dir}/.locks/models--dropbox-dash--faster-whisper-large-v3-turbo*"
  remove_glob_matches "${hf_hub_dir}/.locks/models--ggerganov--whisper.cpp*"

  log "done. next launch should behave like a fresh install."
  return 0
}

main "$@"
