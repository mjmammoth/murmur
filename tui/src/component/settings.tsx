import { createEffect, createMemo, createSignal, For, onMount, Show, type JSX } from "solid-js";
import { useKeyHandler } from "@opentui/solid";
import { type InputRenderable, type KeyEvent } from "@opentui/core";
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

type SettingItem = ToggleSetting | TextSetting;

const SECTION_ORDER: SettingSection[] = ["Recording", "Model", "Audio", "VAD", "Output", "System"];

function boolLabel(value: boolean): string {
  return value ? "on" : "off";
}

function withFallback(value: string | number | null | undefined, fallback = "-"): string {
  if (value === null || value === undefined) return fallback;
  const text = String(value).trim();
  return text.length > 0 ? text : fallback;
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
  const { colors } = useTheme();
  const config = useConfig();
  const backend = useBackend();
  const dialog = useDialog();

  const [query, setQuery] = createSignal("");
  const [selectedIndex, setSelectedIndex] = createSignal(0);
  let searchInput: InputRenderable | undefined;

  const configPath = createMemo(
    () => backend.configFilePath() || "~/.config/whisper-local/config.toml",
  );

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
        id: "model.name",
        section: "Model",
        kind: "text",
        title: "Model Name",
        description: "Default whisper model",
        keywords: ["model", "whisper"],
        value: () => withFallback(cfg?.model.name),
      },
      {
        id: "model.device",
        section: "Model",
        kind: "text",
        title: "Device",
        description: "Runtime device",
        keywords: ["device", "cpu", "cuda", "mps"],
        value: () => withFallback(cfg?.model.device),
      },
      {
        id: "model.compute",
        section: "Model",
        kind: "text",
        title: "Compute Type",
        description: "Quantization and precision",
        keywords: ["compute", "int8", "float16"],
        value: () => withFallback(cfg?.model.compute_type),
      },
      {
        id: "model.language",
        section: "Model",
        kind: "text",
        title: "Language",
        description: "Force language or auto-detect",
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
        kind: "text",
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

  const filteredItems = createMemo(() => {
    const needle = query().trim().toLowerCase();
    if (!needle) return items();

    return items().filter((item) => {
      const searchable = [item.section, item.title, item.description, ...item.keywords]
        .join(" ")
        .toLowerCase();
      return searchable.includes(needle);
    });
  });

  const groupedItems = createMemo(() => {
    const grouped = new Map<SettingSection, SettingItem[]>();

    for (const section of SECTION_ORDER) {
      grouped.set(section, []);
    }

    for (const item of filteredItems()) {
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

  onMount(() => {
    setTimeout(() => {
      if (!searchInput || searchInput.isDestroyed) return;
      searchInput.focus();
    }, 1);
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

  function activateSelected() {
    const item = selectedItem();
    if (!item || item.kind !== "toggle") return;
    item.toggle();
  }

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "settings") return;

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

  const sectionColor = (section: SettingSection) => {
    switch (section) {
      case "Recording":
        return colors().primary;
      case "Model":
        return colors().secondary;
      case "Audio":
        return colors().accent;
      case "VAD":
        return colors().warning;
      case "Output":
        return colors().success;
      case "System":
        return colors().textMuted;
    }
  };

  const valueText = (item: SettingItem) => {
    if (item.kind === "toggle") {
      return item.enabled() ? "on" : "off";
    }
    return item.value();
  };

  const valueColor = (item: SettingItem, active: boolean) => {
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
      height={30}
      backgroundColor={colors().backgroundPanel}
      borderStyle="single"
      borderColor={colors().borderSubtle}
      paddingY={1}
    >
      <box paddingX={3} paddingY={1} flexDirection="row" justifyContent="space-between">
        <text>
          <span style={{ fg: colors().secondary }}>■</span>
          <span style={{ fg: colors().primary }}> Settings</span>
          <span style={{ fg: colors().textMuted }}> / search and toggle</span>
        </text>
        <box backgroundColor={colors().secondary} paddingX={1}>
          <text>
            <span style={{ fg: colors().selectedText }}>esc</span>
          </text>
        </box>
      </box>

      <box paddingX={2}>
        <input
          placeholder="Search settings"
          value={query()}
          focusedBackgroundColor={colors().backgroundElement}
          focusedTextColor={colors().text}
          cursorColor={colors().primary}
          onInput={(value) => {
            setQuery(value);
            setSelectedIndex(0);
          }}
          ref={(r) => {
            searchInput = r;
          }}
        />
      </box>

      <box paddingX={2} paddingTop={1}>
        <text>
          <span style={{ fg: colors().textDim }}>{"-".repeat(80)}</span>
        </text>
      </box>

      <scrollbox flexGrow={1} paddingTop={1}>
        <Show
          when={groupedItems().length > 0}
          fallback={
            <box paddingX={3} paddingY={1}>
              <text fg={colors().textMuted}>No settings match this search.</text>
            </box>
          }
        >
          <box flexDirection="column">
            <For each={groupedItems()}>
              {(group) => (
                <>
                  <box paddingLeft={3} paddingTop={1} paddingBottom={0}>
                    <text>
                      <span style={{ fg: sectionColor(group.section) }}>▌ {group.section}</span>
                    </text>
                  </box>
                  <For each={group.items}>
                    {(item) => {
                      const isActive = () => selectedItem()?.id === item.id;
                      return (
                        <box
                          flexDirection="row"
                          paddingRight={1}
                          backgroundColor={isActive() ? colors().backgroundElement : undefined}
                          onMouseUp={() => {
                            const idx = flatItems().findIndex((entry) => entry.id === item.id);
                            if (idx >= 0) setSelectedIndex(idx);
                            if (item.kind === "toggle") item.toggle();
                          }}
                        >
                          <box
                            width={1}
                            backgroundColor={isActive() ? colors().secondary : colors().borderSubtle}
                          />
                          <box paddingLeft={2} flexDirection="row" width="100%" justifyContent="space-between" gap={2}>
                            <box flexDirection="column" flexGrow={1}>
                              <text>
                                <span style={{ fg: isActive() ? colors().text : colors().text }}>{item.title}</span>
                              </text>
                              <text>
                                <span style={{ fg: colors().textMuted }}>{item.description}</span>
                              </text>
                            </box>
                            <box flexDirection="column" alignItems="flex-end">
                              <text>
                                <span style={{ fg: valueColor(item, isActive()) }}>{valueText(item)}</span>
                              </text>
                              <Show when={item.kind === "text"}>
                                <text>
                                  <span style={{ fg: colors().textDim }}>
                                    read-only
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

      <box paddingX={3} paddingTop={1}>
        <box flexDirection="row" gap={2} alignItems="center">
          <text>
            <span style={{ fg: colors().secondary }}>■</span>
          </text>
          <LegendHint keys="↑/↓" label="navigate" />
          <LegendHint keys="enter" label="toggle" />
          <LegendHint keys="space" label="toggle" />
          <LegendHint keys="←/→" label="set off/on" />
        </box>
      </box>
      <box paddingX={3}>
        <text>
          <span style={{ fg: colors().textDim }}>{configPath()}</span>
        </text>
      </box>
    </box>
  );
}
