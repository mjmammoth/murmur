# Migration Plan: Textual TUI → OpenTUI

This document outlines the migration strategy for whisper.local's TUI from Python/Textual to TypeScript/OpenTUI with SolidJS.

## Overview

### Current Stack (Textual)
- **Language**: Python 3.11+
- **Framework**: Textual 0.60+
- **Architecture**: Class-based App with Screen modals
- **State**: Instance attributes on App class
- **Threading**: `run_worker()` with `call_from_thread()` callbacks

### Target Stack (OpenTUI)
- **Language**: TypeScript
- **Framework**: OpenTUI (`@opentui/core`, `@opentui/solid`)
- **Reactive Layer**: SolidJS
- **Architecture**: Functional components with context providers
- **Threading**: Async/await with Bun runtime

---

## Phase 1: Project Setup

### 1.1 Initialize TypeScript Project

```bash
mkdir -p src/tui
bun init
```

### 1.2 Install Dependencies

```json
{
  "dependencies": {
    "@opentui/core": "^0.1.77",
    "@opentui/solid": "^0.1.77",
    "solid-js": "^1.8.0"
  },
  "devDependencies": {
    "@types/bun": "latest",
    "typescript": "^5.0.0"
  }
}
```

### 1.3 Create File Structure

```
src/tui/
├── app.tsx                 # Root component & render setup
├── routes/
│   └── home.tsx            # Main transcription view
├── component/
│   ├── status-bar.tsx      # Status bar with spinner
│   ├── transcript-list.tsx # Transcript history
│   └── model-manager.tsx   # Model manager dialog
├── context/
│   ├── helper.tsx          # Context creation helper
│   ├── theme.tsx           # Theme provider
│   ├── keybind.tsx         # Keybind provider
│   ├── config.tsx          # App configuration
│   ├── transcriber.tsx     # Transcription state
│   └── audio.tsx           # Audio recording state
├── ui/
│   ├── dialog.tsx          # Dialog wrapper
│   ├── dialog-select.tsx   # List selection component
│   ├── spinner.tsx         # Animated spinner
│   └── list-item.tsx       # Selectable list item
└── util/
    ├── config.ts           # Config file handling
    ├── clipboard.ts        # Clipboard operations
    └── format.ts           # Formatting utilities
```

---

## Phase 2: Component Mapping

### 2.1 Textual → OpenTUI Widget Mapping

| Textual | OpenTUI | Notes |
|---------|---------|-------|
| `App` | `render()` + root component | Functional entry point |
| `Screen` | Dialog in context stack | Modal via `useDialog()` |
| `Static` | `<text>` | Direct text rendering |
| `ListView` | `<scrollbox>` + custom items | Manual item rendering |
| `ListItem` | `<box>` with selection state | Use store for selection |
| `Container` | `<box>` | Flexbox layout |
| `Footer` | `<box>` at bottom | Manual key hints |
| CSS selectors | Inline style props | `backgroundColor`, `fg`, etc. |

### 2.2 Key Binding Migration

**Textual:**
```python
BINDINGS = [
    Binding("q", "quit", "Quit"),
    Binding("c", "copy_latest", "Copy"),
]
```

**OpenTUI:**
```typescript
// In keybind context
const bindings = {
  quit: { key: "q", description: "Quit" },
  copy_latest: { key: "c", description: "Copy" },
}

// In component
useKeyboard((evt) => {
  if (keybind.match("quit", evt)) {
    exit()
  }
  if (keybind.match("copy_latest", evt)) {
    copyLatest()
  }
})
```

### 2.3 State Migration

**Textual App State:**
```python
class WhisperApp(App):
    _recording: bool = False
    _auto_copy: bool = False
    _entries: list[TranscriptEntry] = []
    _status_message: str = ""
```

**OpenTUI with SolidJS Store:**
```typescript
// context/transcriber.tsx
const [store, setStore] = createStore({
  recording: false,
  autoCopy: false,
  entries: [] as TranscriptEntry[],
  statusMessage: "",
})
```

---

## Phase 3: Core Component Implementation

### 3.1 App Entry Point

```typescript
// app.tsx
import { render } from "@opentui/solid"
import { ErrorBoundary } from "solid-js"

render(
  () => (
    <ErrorBoundary fallback={(err) => <text fg="red">{err.message}</text>}>
      <ConfigProvider>
        <ThemeProvider>
          <KeybindProvider>
            <TranscriberProvider>
              <AudioProvider>
                <DialogProvider>
                  <ToastProvider>
                    <Home />
                  </ToastProvider>
                </DialogProvider>
              </AudioProvider>
            </TranscriberProvider>
          </KeybindProvider>
        </ThemeProvider>
      </ConfigProvider>
    </ErrorBoundary>
  ),
  {
    targetFps: 60,
    exitOnCtrlC: false,
  }
)
```

### 3.2 Main Screen (Home)

```typescript
// routes/home.tsx
export function Home() {
  const { theme } = useTheme()
  const dimensions = useTerminalDimensions()

  return (
    <box
      flexDirection="column"
      width={dimensions().width}
      height={dimensions().height}
    >
      <StatusBar />
      <TranscriptList />
      <KeybindFooter />
    </box>
  )
}
```

### 3.3 Status Bar with Spinner

```typescript
// component/status-bar.tsx
const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

export function StatusBar() {
  const { theme } = useTheme()
  const transcriber = useTranscriber()
  const [spinnerIndex, setSpinnerIndex] = createSignal(0)

  // Animate spinner
  createEffect(() => {
    if (transcriber.busy) {
      const interval = setInterval(() => {
        setSpinnerIndex((i) => (i + 1) % SPINNER_FRAMES.length)
      }, 80)
      onCleanup(() => clearInterval(interval))
    }
  })

  return (
    <box
      paddingLeft={2}
      paddingRight={2}
      paddingTop={1}
      paddingBottom={1}
      backgroundColor={theme.backgroundPanel}
    >
      <Show when={transcriber.busy}>
        <text fg={theme.primary}>{SPINNER_FRAMES[spinnerIndex()]}</text>
      </Show>
      <text fg={theme.text}>{transcriber.statusMessage}</text>
    </box>
  )
}
```

### 3.4 Transcript List

```typescript
// component/transcript-list.tsx
export function TranscriptList() {
  const { theme } = useTheme()
  const transcriber = useTranscriber()
  const [selected, setSelected] = createSignal(0)
  let scrollRef: ScrollBoxRenderable

  // Auto-scroll to latest
  createEffect(() => {
    const count = transcriber.entries.length
    if (count > 0) {
      scrollRef?.scrollTo({ y: Infinity })
    }
  })

  useKeyboard((evt) => {
    if (evt.name === "up") {
      setSelected((s) => Math.max(0, s - 1))
    }
    if (evt.name === "down") {
      setSelected((s) => Math.min(transcriber.entries.length - 1, s + 1))
    }
  })

  return (
    <scrollbox
      ref={(r) => (scrollRef = r)}
      flexGrow={1}
      paddingLeft={1}
      paddingRight={1}
    >
      <For each={transcriber.entries}>
        {(entry, index) => (
          <TranscriptItem
            entry={entry}
            selected={selected() === index()}
          />
        )}
      </For>
    </scrollbox>
  )
}
```

### 3.5 Model Manager Dialog

```typescript
// component/model-manager.tsx
export function ModelManagerDialog() {
  const dialog = useDialog()
  const { theme } = useTheme()
  const [models, setModels] = createSignal<Model[]>([])
  const [selected, setSelected] = createSignal(0)

  onMount(async () => {
    const list = await loadModels()
    setModels(list)
  })

  useKeyboard((evt) => {
    if (evt.name === "escape") {
      dialog.clear()
    }
    if (evt.name === "p") {
      pullModel(models()[selected()])
    }
    if (evt.name === "r") {
      removeModel(models()[selected()])
    }
  })

  return (
    <Dialog onClose={() => dialog.clear()}>
      <box flexDirection="column" gap={1}>
        <text fg={theme.text} attributes={TextAttributes.BOLD}>
          Models
        </text>
        <scrollbox maxHeight={10}>
          <For each={models()}>
            {(model, index) => (
              <ModelItem
                model={model}
                selected={selected() === index()}
              />
            )}
          </For>
        </scrollbox>
        <text fg={theme.textMuted}>
          [p] pull  [r] remove  [d] set default  [esc] close
        </text>
      </box>
    </Dialog>
  )
}
```

---

## Phase 4: Context Providers

### 4.1 Context Helper

```typescript
// context/helper.tsx
export function createSimpleContext<T, Props extends Record<string, any>>(input: {
  name: string
  init: (props: Props) => T
}) {
  const ctx = createContext<T>()

  return {
    provider: (props: ParentProps<Props>) => {
      const init = input.init(props)
      return <ctx.Provider value={init}>{props.children}</ctx.Provider>
    },
    use() {
      const value = useContext(ctx)
      if (!value) throw new Error(`${input.name} context not found`)
      return value
    },
  }
}
```

### 4.2 Transcriber Context

```typescript
// context/transcriber.tsx
export const { use: useTranscriber, provider: TranscriberProvider } =
  createSimpleContext({
    name: "Transcriber",
    init: () => {
      const [store, setStore] = createStore({
        entries: [] as TranscriptEntry[],
        recording: false,
        busy: false,
        busyHint: "",
        statusMessage: "",
        modelName: "",
      })

      return {
        get entries() { return store.entries },
        get recording() { return store.recording },
        get busy() { return store.busy },
        get statusMessage() { return store.statusMessage },

        addEntry(entry: TranscriptEntry) {
          setStore("entries", (e) => [...e, entry])
        },
        setRecording(value: boolean) {
          setStore("recording", value)
        },
        setBusy(busy: boolean, hint?: string) {
          batch(() => {
            setStore("busy", busy)
            setStore("busyHint", hint ?? "")
          })
        },
      }
    },
  })
```

### 4.3 Config Context

```typescript
// context/config.tsx
interface AppConfig {
  model: { name: string; device: string }
  hotkey: { key: string; modifiers: string[] }
  audio: { noiseSuppression: boolean; vad: boolean }
  output: { autoCopy: boolean; filePath?: string }
}

export const { use: useConfig, provider: ConfigProvider } =
  createSimpleContext({
    name: "Config",
    init: () => {
      const configPath = path.join(os.homedir(), ".config/whisper.local/config.toml")
      const [config, setConfig] = createStore<AppConfig>(loadConfig(configPath))

      // Auto-save on changes
      createEffect(() => {
        saveConfig(configPath, config)
      })

      return {
        get config() { return config },
        update<K extends keyof AppConfig>(key: K, value: AppConfig[K]) {
          setStore(key, value)
        },
      }
    },
  })
```

---

## Phase 5: Integration Challenges

### 5.1 Audio Recording

The current Python implementation uses `sounddevice`. Options for TypeScript:

**Option A: Native Bun FFI**
```typescript
// Use Bun's FFI to call native audio APIs
import { dlopen, FFIType } from "bun:ffi"
```

**Option B: Subprocess**
```typescript
// Spawn Python subprocess for audio capture
const proc = Bun.spawn(["python", "-m", "whisper_local.audio_bridge"])
```

**Option C: WebSocket Bridge**
```typescript
// Python backend sends audio over WebSocket
const ws = new WebSocket("ws://localhost:8765")
ws.onmessage = (event) => {
  const audioData = event.data
  transcribe(audioData)
}
```

**Recommended**: Option C (WebSocket Bridge) for initial migration, then refactor to Option A for full native solution.

### 5.2 Transcription (faster-whisper)

The `faster-whisper` library is Python-only. Options:

**Option A: HTTP API**
```typescript
// Expose faster-whisper as HTTP endpoint
const response = await fetch("http://localhost:8000/transcribe", {
  method: "POST",
  body: audioBuffer,
})
const { text } = await response.json()
```

**Option B: whisper.cpp via FFI**
```typescript
// Use whisper.cpp directly via Bun FFI
import { whisper_init, whisper_full } from "./bindings/whisper"
```

**Recommended**: Start with Option A, migrate to Option B for performance.

### 5.3 Global Hotkey

Current implementation uses macOS Quartz APIs. For TypeScript:

**Option A: Native addon**
```typescript
// Use node-global-key-listener or similar
import { GlobalKeyboardListener } from "node-global-key-listener"
```

**Option B: Separate daemon**
```typescript
// Python daemon handles hotkey, signals via IPC
```

### 5.4 Noise Suppression & VAD

Keep these as Python components initially, expose via IPC or HTTP.

---

## Phase 6: Migration Steps

### Step 1: Create Hybrid Architecture
- Keep Python backend for audio, transcription, hotkey
- Build OpenTUI frontend that communicates via WebSocket/HTTP
- Validate UI parity with Textual version

### Step 2: Migrate Configuration
- Port `config.py` dataclasses to TypeScript interfaces
- Implement TOML reading/writing in TypeScript
- Ensure backward compatibility with existing config files

### Step 3: Build Core UI Components
1. Status bar with spinner animation
2. Transcript list with selection
3. Model manager dialog
4. Toast notifications
5. Keybind footer

### Step 4: Implement State Management
1. Create all context providers
2. Wire up WebSocket messages to state updates
3. Implement reactive UI updates

### Step 5: Add Native Integrations (Optional)
- Replace Python audio with native Bun FFI
- Integrate whisper.cpp for transcription
- Native hotkey listener

---

## Phase 7: Testing Strategy

### 7.1 Component Tests
```typescript
// Use solid-testing-library
import { render, screen } from "@solidjs/testing-library"

test("StatusBar shows spinner when busy", () => {
  render(() => (
    <TranscriberProvider>
      <StatusBar />
    </TranscriberProvider>
  ))
  // assertions
})
```

### 7.2 Integration Tests
- Test WebSocket message handling
- Test config file round-trips
- Test keyboard navigation

### 7.3 Manual Testing Checklist
- [ ] App launches and displays status bar
- [ ] Transcript list scrolls and selects correctly
- [ ] Model manager opens/closes with correct keybinds
- [ ] Copy to clipboard works
- [ ] Auto-copy toggle persists
- [ ] Theme colors apply correctly
- [ ] Spinner animates during long operations

---

## Timeline Estimate

| Phase | Tasks | Complexity |
|-------|-------|-----------|
| 1 | Project setup | Low |
| 2 | Component mapping design | Low |
| 3 | Core components | Medium |
| 4 | Context providers | Medium |
| 5 | Integration (hybrid) | High |
| 6 | Full migration | High |
| 7 | Testing | Medium |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Audio capture complexity | High | Keep Python backend initially |
| faster-whisper unavailable in TS | High | HTTP bridge or whisper.cpp |
| Platform-specific hotkeys | Medium | Separate daemon process |
| Performance regression | Medium | Profile and optimize |
| Config compatibility | Low | Strict schema validation |

---

## Success Criteria

1. **Feature parity**: All Textual features work in OpenTUI
2. **Performance**: No perceivable latency increase
3. **Maintainability**: Cleaner separation of concerns
4. **Extensibility**: Easier to add new features
5. **User experience**: Polished, responsive UI

---

## References

- [OpenTUI Repository](https://github.com/sst/opentui)
- [SolidJS Documentation](https://www.solidjs.com/docs/latest)
- [opencode TUI Implementation](../opencode/packages/opencode/src/cli/cmd/tui/)
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp)
