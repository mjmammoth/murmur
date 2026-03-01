# ADR: Service/TUI and Platform Contracts

## Status
Accepted

## Date
2026-02-23

## Context
`murmur` is evolving from a single process (bridge + TUI lifecycle coupled) to a service-first model with:

- background backend lifecycle independent from the TUI
- attachable/detachable TUI sessions
- platform-specific capability handling without forcing macOS-only imports on Linux/Windows

To avoid repeated refactors, we need explicit contracts for:

- platform capabilities and providers
- backend service state and storage ownership
- bridge-to-client message shape for transcript history

## Decision
We define and own these contracts:

1. Platform contracts
- `src/murmur/platform/capabilities.py`
  - `PlatformCapabilities` includes:
    - `hotkey_capture`
    - `hotkey_swallow`
    - `status_indicator`
    - `auto_paste`
    - `hotkey_guidance`
- `src/murmur/platform/providers.py`
  - `HotkeyProvider`
  - `StatusIndicatorProvider`
  - `PasteProvider`
- `src/murmur/platform/factory.py`
  - capability detection
  - provider construction
  - hotkey validation

2. Service state contracts
- `src/murmur/service_state.py`
  - state directory: `~/.local/state/murmur`
  - service file: `service.json`
  - transcript database: `transcripts.sqlite3`
  - typed `ServiceState` and `ServiceStatus`

3. Transcript persistence contract
- `src/murmur/transcript_store.py`
  - SQLite-backed transcript records
  - bounded retention via config (`history.max_entries`)
  - stable transcript message metadata (`id`, `created_at`)

## Consequences
- core runtime startup is platform-safe: macOS-only imports stay behind provider boundaries.
- bridge owns transcript history and sends replay on client connect.
- service process and TUI become operationally independent.
- distribution changes can proceed without reworking runtime contracts again.

## Out of Scope
- desktop GUI packaging
- cloud telemetry or remote state sync
