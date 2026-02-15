import { createEffect, createMemo, createSignal, For, Show, type JSX } from "solid-js";
import { useKeyHandler, useTerminalDimensions } from "@opentui/solid";
import { type KeyEvent, type ScrollBoxRenderable } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useDialog } from "../context/dialog";
import { useConfig } from "../context/config";
import { useBackend } from "../context/backend";

type SettingSection = "Recording" | "Model" | "Audio" | "VAD" | "Output" | "System";

interface SettingBase {
  id: string;
  section: SettingSection;
  title: string;
  description: string;
  keywords: string[];
}

interface ToggleSetting extends SettingBase {
  kind: "toggle";
  enabled: () => boolean;
  toggle: () => void;
}

interface TextSetting extends SettingBase {
  kind: "text";
  value: () => string;
}

interface HotkeySetting extends SettingBase {
  kind: "hotkey";
  value: () => string;
}

type SettingItem = ToggleSetting | TextSetting | HotkeySetting;

const SECTION_ORDER: SettingSection[] = ["Recording", "Model", "Audio", "VAD", "Output", "System"];
const HOTKEY_KEY_SETTING_ID = "hotkey.key";
const MODIFIER_KEYS = new Set(["shift", "ctrl", "control", "meta", "cmd", "command", "alt", "option"]);
const SHIFTED_DIGIT_SYMBOL_TO_KEY: Record<string, string> = {
  "!": "1",
  "@": "2",
  "#": "3",
  "$": "4",
  "%": "5",
  "^": "6",
  "&": "7",
  "*": "8",
  "(": "9",
  ")": "0",
};

function boolLabel(value: boolean): string {
  return value ? "on" : "off";
}

function withFallback(value: string | number | null | undefined, fallback = "-"): string {
  if (value === null || value === undefined) return fallback;
  const text = String(value).trim();
  return text.length > 0 ? text : fallback;
}

function normalizeHotkeyBaseKey(name: string): { baseKey: string | null; inferredShift: boolean } {
  if (SHIFTED_DIGIT_SYMBOL_TO_KEY[name]) {
    return { baseKey: SHIFTED_DIGIT_SYMBOL_TO_KEY[name]!, inferredShift: true };
  }

  const lowered = name.toLowerCase();
  if (/^[a-z0-9]$/.test(lowered)) return { baseKey: lowered, inferredShift: false };
  if (/^f([1-9]|1[0-2])$/.test(lowered)) return { baseKey: lowered, inferredShift: false };

  switch (lowered) {
    case "space":
      return { baseKey: "space", inferredShift: false };
    case "return":
    case "enter":
      return { baseKey: "return", inferredShift: false };
    case "tab":
      return { baseKey: "tab", inferredShift: false };
    case "escape":
    case "esc":
      return { baseKey: "escape", inferredShift: false };
    default:
      return { baseKey: null, inferredShift: false };
  }
}

function formatHotkeyFromEvent(key: KeyEvent): { hotkey: string | null; error?: string; modifierOnly?: boolean } {
  const caseInferredShift = key.name.length === 1 && key.name !== key.name.toLowerCase();
  const name = key.name.toLowerCase();
  if (MODIFIER_KEYS.has(name)) return { hotkey: null, modifierOnly: true };

  const { baseKey, inferredShift } = normalizeHotkeyBaseKey(key.name);
  const hasShift = key.shift || caseInferredShift || inferredShift;
  if (!baseKey) {
    return { hotkey: null, error: `Unsupported key: ${key.name}` };
  }

  const parts: string[] = [];
  if (key.meta) parts.push("cmd");
  if (key.ctrl) parts.push("ctrl");
  if (key.option) parts.push("option");
  if (hasShift) parts.push("shift");
  parts.push(baseKey);

  return { hotkey: parts.join("+") };
}

function LegendHint(props: { keys: string; label: string }): JSX.Element {
  const { colors } = useTheme();

  return (
    <box flexDirection="row" alignItems="center" gap={1}>
      <box backgroundColor={colors().secondary} paddingX={1}>
        <text>
          <span style={{ fg: colors().selectedText }}>{props.keys}</span>
        </text>
      </box>
      <text>
        <span style={{ fg: colors().textMuted }}>{props.label}</span>
      </text>
    </box>
  );
}

export function Settings(): JSX.Element {
  const { colors, theme } = useTheme();
  const config = useConfig();
  const backend = useBackend();
  const dialog = useDialog();
  const terminal = useTerminalDimensions();

  const [selectedIndex, setSelectedIndex] = createSignal(0);
  const [listeningSettingId, setListeningSettingId] = createSignal<string | null>(null);
  const [captureError, setCaptureError] = createSignal("");
  let settingsScroll: ScrollBoxRenderable | undefined;

  const configPath = createMemo(
    () => backend.configFilePath() || "~/.config/whisper.local/config.toml",
  );

  const modalHeight = createMemo(() => {
    const minHeight = 20;
    const maxHeight = Math.max(minHeight, terminal().height - 4);
    const preferred = Math.floor(terminal().height * 0.8);
    return Math.max(minHeight, Math.min(preferred, maxHeight));
  });

  const selectedInstalledModelName = createMemo(() => {
    const selected = config.config()?.model.name;
    if (!selected) return "none";
    const match = backend.models().find((model) => model.name === selected);
    return match?.installed ? selected : "none";
  });

  const items = createMemo<SettingItem[]>(() => {
    const cfg = config.config();

    return [
      {
        id: "recording.noise",
        section: "Recording",
        kind: "toggle",
        title: "Noise Suppression",
        description: "RNNoise denoise pass before transcription",
        keywords: ["noise", "rnnoise", "cleanup"],
        enabled: config.noiseEnabled,
        toggle: config.toggleNoise,
      },
      {
        id: "recording.vad",
        section: "Recording",
        kind: "toggle",
        title: "Voice Activity Detection",
        description: "Trim silence at the beginning and end",
        keywords: ["vad", "silence", "trim"],
        enabled: config.vadEnabled,
        toggle: config.toggleVad,
      },
      {
        id: "recording.autocopy",
        section: "Recording",
        kind: "toggle",
        title: "Auto Copy",
        description: "Copy transcript text automatically",
        keywords: ["clipboard", "copy", "automatic"],
        enabled: config.autoCopy,
        toggle: config.toggleAutoCopy,
      },
      {
        id: "recording.autopaste",
        section: "Recording",
        kind: "toggle",
        title: "Auto Paste",
        description: "Paste transcript text into focused app",
        keywords: ["clipboard", "paste", "automatic"],
        enabled: config.autoPaste,
        toggle: config.toggleAutoPaste,
      },
      {
        id: "model.name",
        section: "Model",
        kind: "text",
        title: "Selected Model",
        description: "Press enter to open model manager",
        keywords: ["model", "whisper"],
        value: () => selectedInstalledModelName(),
      },
      {
        id: "model.backend",
        section: "Model",
        kind: "text",
        title: "Backend",
        description: "Press enter to choose transcription backend",
        keywords: ["backend", "faster-whisper", "whisper.cpp"],
        value: () => withFallback(cfg?.model.backend, "faster-whisper"),
      },
      {
        id: "model.device",
        section: "Model",
        kind: "text",
        title: "Device",
        description: "Press enter to choose runtime device",
        keywords: ["device", "cpu", "cuda", "mps"],
        value: () => withFallback(cfg?.model.device),
      },
      {
        id: "model.compute",
        section: "Model",
        kind: "text",
        title: "Compute Type",
        description: "Press enter to choose quantization",
        keywords: ["compute", "int8", "float16"],
        value: () => withFallback(cfg?.model.compute_type),
      },
      {
        id: "model.language",
        section: "Model",
        kind: "text",
        title: "Language",
        description: "Press enter to search and choose language",
        keywords: ["language", "locale", "auto"],
        value: () => withFallback(cfg?.model.language, "auto"),
      },
      {
        id: "model.path",
        section: "Model",
        kind: "text",
        title: "Local Model Path",
        description: "Optional local model override",
        keywords: ["path", "filesystem", "cache"],
        value: () => withFallback(cfg?.model.path, "default cache"),
      },
      {
        id: "hotkey.mode",
        section: "Audio",
        kind: "text",
        title: "Hotkey Mode",
        description: "Push-to-talk or toggle",
        keywords: ["hotkey", "mode", "ptt", "toggle"],
        value: () => withFallback(cfg?.hotkey.mode),
      },
      {
        id: "hotkey.key",
        section: "Audio",
        kind: "hotkey",
        title: "Hotkey Key",
        description: "Global shortcut for recording",
        keywords: ["hotkey", "shortcut", "key"],
        value: () => withFallback(cfg?.hotkey.key),
      },
      {
        id: "audio.sample_rate",
        section: "Audio",
        kind: "text",
        title: "Sample Rate",
        description: "Audio capture sample rate",
        keywords: ["sample", "hz", "audio"],
        value: () => withFallback(cfg?.audio.sample_rate),
      },
      {
        id: "audio.noise.level",
        section: "Audio",
        kind: "text",
        title: "Noise Level",
        description: "RNNoise suppression level",
        keywords: ["noise", "level", "rnnoise"],
        value: () => withFallback(cfg?.audio.noise_suppression.level),
      },
      {
        id: "vad.aggressiveness",
        section: "VAD",
        kind: "text",
        title: "Aggressiveness",
        description: "VAD sensitivity",
        keywords: ["vad", "aggressive", "sensitivity"],
        value: () => withFallback(cfg?.vad.aggressiveness),
      },
      {
        id: "vad.min_speech",
        section: "VAD",
        kind: "text",
        title: "Min Speech ms",
        description: "Minimum speech segment",
        keywords: ["vad", "speech", "timing"],
        value: () => withFallback(cfg?.vad.min_speech_ms),
      },
      {
        id: "vad.max_silence",
        section: "VAD",
        kind: "text",
        title: "Max Silence ms",
        description: "Silence allowed before split",
        keywords: ["vad", "silence", "timing"],
        value: () => withFallback(cfg?.vad.max_silence_ms),
      },
      {
        id: "output.clipboard",
        section: "Output",
        kind: "text",
        title: "Clipboard Output",
        description: "Clipboard writes in base config",
        keywords: ["output", "clipboard"],
        value: () => boolLabel(Boolean(cfg?.output.clipboard)),
      },
      {
        id: "output.file.enabled",
        section: "Output",
        kind: "text",
        title: "File Output Enabled",
        description: "Append transcripts to file",
        keywords: ["output", "file", "write"],
        value: () => boolLabel(Boolean(cfg?.output.file.enabled)),
      },
      {
        id: "output.file.path",
        section: "Output",
        kind: "text",
        title: "Output File Path",
        description: "Destination path for file output",
        keywords: ["output", "file", "path"],
        value: () => withFallback(cfg?.output.file.path),
      },
      {
        id: "bridge.host",
        section: "System",
        kind: "text",
        title: "Bridge Host",
        description: "WebSocket bridge host",
        keywords: ["bridge", "host", "network"],
        value: () => withFallback(cfg?.bridge.host),
      },
      {
        id: "bridge.port",
        section: "System",
        kind: "text",
        title: "Bridge Port",
        description: "WebSocket bridge port",
        keywords: ["bridge", "port", "network"],
        value: () => withFallback(cfg?.bridge.port),
      },
      {
        id: "ui.theme",
        section: "System",
        kind: "text",
        title: "Theme",
        description: "Press enter to choose UI theme",
        keywords: ["theme", "appearance", "color", "palette"],
        value: () => withFallback(theme().label),
      },
      {
        id: "system.config_path",
        section: "System",
        kind: "text",
        title: "Config Path",
        description: "On-disk config location",
        keywords: ["config", "path", "toml"],
        value: () => configPath(),
      },
    ];
  });

  const groupedItems = createMemo(() => {
    const grouped = new Map<SettingSection, SettingItem[]>();

    for (const section of SECTION_ORDER) {
      grouped.set(section, []);
    }

    for (const item of items()) {
      grouped.get(item.section)?.push(item);
    }

    return SECTION_ORDER
      .map((section) => ({ section, items: grouped.get(section) ?? [] }))
      .filter((group) => group.items.length > 0);
  });

  const flatItems = createMemo(() => groupedItems().flatMap((group) => group.items));

  const selectedItem = createMemo(() => {
    const list = flatItems();
    if (list.length === 0) return null;
    return list[selectedIndex()] ?? list[0] ?? null;
  });

  const isModelManagerSetting = (id: string) => id === "model.name";
  const isSelectorSetting = (id: string) =>
    id === "model.backend" || id === "model.device" || id === "model.compute" || id === "model.language";
  const isThemeSetting = (id: string) => id === "ui.theme";

  createEffect(() => {
    const list = flatItems();
    if (list.length === 0) {
      setSelectedIndex(0);
      return;
    }

    if (selectedIndex() >= list.length) {
      setSelectedIndex(list.length - 1);
    }
  });

  createEffect(() => {
    if (dialog.currentDialog()?.type !== "settings" && listeningSettingId()) {
      cancelHotkeyCapture();
    }
  });

  const itemScrollOffsets = createMemo(() => {
    const offsets = new Map<string, number>();
    let lineOffset = 0;

    for (const group of groupedItems()) {
      lineOffset += 2;
      for (const item of group.items) {
        offsets.set(item.id, lineOffset);
        lineOffset += 2;
      }
    }

    return offsets;
  });

  createEffect(() => {
    const active = selectedItem();
    if (!active) return;
    if (dialog.currentDialog()?.type !== "settings") return;
    if (!settingsScroll || settingsScroll.isDestroyed) return;

    const offset = itemScrollOffsets().get(active.id);
    if (offset === undefined) return;

    const rowTop = offset;
    const rowBottom = rowTop + 1;
    const viewportHeight = settingsScroll.viewport.height;
    if (viewportHeight <= 0) return;

    const currentTop = settingsScroll.scrollTop;
    const topMargin = 1;
    const bottomMargin = 1;
    const minVisibleTop = currentTop + topMargin;
    const maxVisibleBottom = currentTop + viewportHeight - 1 - bottomMargin;

    if (rowTop < minVisibleTop) {
      settingsScroll.scrollTo(Math.max(0, rowTop - topMargin));
      return;
    }

    if (rowBottom > maxVisibleBottom) {
      const nextTop = rowBottom - (viewportHeight - 1 - bottomMargin);
      settingsScroll.scrollTo(Math.max(0, nextTop));
    }
  });

  function moveSelection(delta: number) {
    const list = flatItems();
    if (list.length === 0) return;

    let next = selectedIndex() + delta;
    if (next < 0) next = list.length - 1;
    if (next >= list.length) next = 0;
    setSelectedIndex(next);
  }

  function setToggleValue(item: ToggleSetting, value: boolean) {
    if (item.enabled() !== value) item.toggle();
  }

  function beginHotkeyCapture() {
    setListeningSettingId(null);
    setCaptureError("");
    dialog.openDialog("hotkey", { returnToSettings: true });
  }

  function cancelHotkeyCapture() {
    setListeningSettingId(null);
    setCaptureError("");
  }

  function submitHotkeyCapture(key: KeyEvent) {
    const parsed = formatHotkeyFromEvent(key);
    if (parsed.modifierOnly) {
      setCaptureError("Press a non-modifier key");
      return;
    }
    if (parsed.error || !parsed.hotkey) {
      setCaptureError(parsed.error ?? "Unsupported key");
      return;
    }

    backend.send({ type: "set_hotkey", hotkey: parsed.hotkey });
    setListeningSettingId(null);
    setCaptureError("");
  }

  function openSettingDialog(id: string) {
    if (isModelManagerSetting(id)) {
      dialog.openDialog("model-manager", { returnToSettings: true });
      return true;
    }
    if (isSelectorSetting(id)) {
      dialog.openDialog("settings-select", { settingId: id, returnToSettings: true });
      return true;
    }
    if (isThemeSetting(id)) {
      dialog.openDialog("theme-picker", { returnToSettings: true });
      return true;
    }
    return false;
  }

  function activateSelected() {
    const item = selectedItem();
    if (!item) return;

    if (openSettingDialog(item.id)) return;

    if (item.kind === "toggle") {
      item.toggle();
      return;
    }
    if (item.kind === "hotkey") {
      beginHotkeyCapture();
    }
  }

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "settings") return;

    if (listeningSettingId()) {
      key.preventDefault();

      if (key.name === "escape") {
        cancelHotkeyCapture();
        return;
      }

      submitHotkeyCapture(key);
      return;
    }

    switch (key.name) {
      case "escape":
        dialog.closeDialog();
        break;
      case "up":
        key.preventDefault();
        moveSelection(-1);
        break;
      case "down":
        key.preventDefault();
        moveSelection(1);
        break;
      case "left": {
        const item = selectedItem();
        if (item?.kind === "toggle") {
          key.preventDefault();
          setToggleValue(item, false);
        }
        break;
      }
      case "right": {
        const item = selectedItem();
        if (item?.kind === "toggle") {
          key.preventDefault();
          setToggleValue(item, true);
        }
        break;
      }
      case "space":
      case "return":
      case "enter":
        key.preventDefault();
        activateSelected();
        break;
    }
  });

  const valueText = (item: SettingItem) => {
    if (item.kind === "hotkey" && listeningSettingId() === item.id) {
      return "listening...";
    }
    if (item.kind === "toggle") {
      return item.enabled() ? "on" : "off";
    }
    return item.value();
  };

  const descriptionText = (item: SettingItem) => {
    if (item.kind !== "hotkey") return item.description;
    if (captureError()) return captureError();
    return "Press enter to open hotkey modal";
  };

  const valueColor = (item: SettingItem, active: boolean) => {
    if (item.kind === "hotkey") {
      return active ? colors().text : colors().secondary;
    }
    if (item.kind === "toggle") {
      if (item.enabled()) return colors().success;
      return active ? colors().textMuted : colors().textDim;
    }
    if (active) return colors().text;
    return colors().secondary;
  };

  return (
    <box
      flexDirection="column"
      width={86}
      height={modalHeight()}
      backgroundColor={colors().backgroundPanel}
      paddingY={1}
    >
      <box paddingX={3} paddingTop={1} paddingBottom={0} flexDirection="column" flexShrink={0}>
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>Settings</span>
          </text>
          <box flexDirection="row" alignItems="center" gap={2}>
            <text>
              <span style={{ fg: colors().textMuted }}>toggle and edit</span>
            </text>
            <box backgroundColor={colors().secondary} paddingX={1}>
              <text>
                <span style={{ fg: colors().selectedText }}>esc</span>
              </text>
            </box>
          </box>
        </box>
        <box flexDirection="row" width="100%" marginTop={0}>
          <box width={3} borderStyle="single" border={["bottom"]} borderColor={colors().secondary} />
          <box flexGrow={1} borderStyle="single" border={["bottom"]} borderColor={colors().borderSubtle} />
        </box>
      </box>

      <scrollbox
        flexGrow={1}
        flexShrink={1}
        paddingTop={1}
        ref={(r: ScrollBoxRenderable) => {
          settingsScroll = r;
        }}
      >
        <Show
          when={groupedItems().length > 0}
          fallback={
            <box paddingX={3} paddingY={1}>
              <text fg={colors().textMuted}>No settings available.</text>
            </box>
          }
        >
          <box flexDirection="column">
            <For each={groupedItems()}>
              {(group) => (
                <>
                  <box paddingLeft={3} paddingTop={1} paddingBottom={0}>
                    <text>
                      <span style={{ fg: colors().accent, bold: true }}>{group.section}</span>
                    </text>
                  </box>
                  <For each={group.items}>
                    {(item) => {
                      const isActive = () => selectedItem()?.id === item.id;
                      return (
                        <box
                          id={item.id}
                          role="option"
                          aria-selected={isActive()}
                          flexDirection="row"
                          paddingRight={1}
                          backgroundColor={isActive() ? colors().backgroundElement : undefined}
                          onMouseUp={() => {
                            const idx = flatItems().findIndex((entry) => entry.id === item.id);
                            if (idx >= 0) setSelectedIndex(idx);

                            if (openSettingDialog(item.id)) return;

                            if (item.kind === "toggle") item.toggle();
                            if (item.kind === "hotkey") beginHotkeyCapture();
                          }}
                        >
                          <box
                            width={1}
                            backgroundColor={isActive() ? colors().secondary : undefined}
                          />
                          <box paddingLeft={2} flexDirection="row" width="100%" justifyContent="space-between" gap={2}>
                            <box flexDirection="column" flexGrow={1}>
                              <text>
                                <span style={{ fg: isActive() ? colors().text : colors().text }}>{item.title}</span>
                              </text>
                              <text>
                                <span
                                  style={{
                                    fg:
                                      item.kind === "hotkey" && listeningSettingId() === item.id && captureError()
                                        ? colors().error
                                        : colors().textMuted,
                                  }}
                                >
                                  {descriptionText(item)}
                                </span>
                              </text>
                            </box>
                            <box flexDirection="column" alignItems="flex-end">
                              <text>
                                <span style={{ fg: valueColor(item, isActive()) }}>{valueText(item)}</span>
                              </text>
                              <Show
                                when={
                                  item.kind === "text" &&
                                  !isModelManagerSetting(item.id) &&
                                  !isSelectorSetting(item.id) &&
                                  !isThemeSetting(item.id)
                                }
                              >
                                <text>
                                  <span style={{ fg: colors().textDim }}>
                                    read-only
                                  </span>
                                </text>
                              </Show>
                              <Show when={isModelManagerSetting(item.id)}>
                                <text>
                                  <span style={{ fg: colors().textDim }}>
                                    open manager
                                  </span>
                                </text>
                              </Show>
                              <Show when={isSelectorSetting(item.id)}>
                                <text>
                                  <span style={{ fg: colors().textDim }}>
                                    open selector
                                  </span>
                                </text>
                              </Show>
                              <Show when={isThemeSetting(item.id)}>
                                <text>
                                  <span style={{ fg: colors().textDim }}>
                                    open picker
                                  </span>
                                </text>
                              </Show>
                              <Show when={item.kind === "hotkey"}>
                                <text>
                                  <span style={{ fg: colors().textDim }}>
                                    open modal
                                  </span>
                                </text>
                              </Show>
                            </box>
                          </box>
                        </box>
                      );
                    }}
                  </For>
                </>
              )}
            </For>
          </box>
        </Show>
      </scrollbox>

      <box paddingX={3} paddingTop={1} flexShrink={0}>
        <box flexDirection="row" gap={2} alignItems="center">
          <LegendHint keys="↑/↓" label="navigate" />
          <LegendHint keys="enter" label="activate" />
          <LegendHint keys="space" label="activate" />
          <LegendHint keys="←/→" label="set off/on" />
        </box>
      </box>
      <box paddingX={3} flexShrink={0}>
        <text>
          <span style={{ fg: colors().textDim }}>{configPath()}</span>
        </text>
      </box>
    </box>
  );
}
