import { createEffect, createMemo, createSignal, For, onCleanup, Show, type JSX } from "solid-js";
import { useKeyHandler, useTerminalDimensions } from "@opentui/solid";
import { type KeyEvent, type ScrollBoxRenderable } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useDialog } from "../context/dialog";
import { useConfig } from "../context/config";
import { useBackend } from "../context/backend";
import { formatDeviceLabel } from "../util/format";

type SettingSection = "Capture" | "Model" | "Output" | "Appearance" | "Advanced";
type ControlKind = "toggle" | "select" | "open" | "edit" | "read-only";

type SelectSettingId =
  | "model.runtime"
  | "model.device"
  | "model.compute"
  | "model.language"
  | "audio.sample_rate"
  | "vad.aggressiveness";

type EditSettingId = "model.path" | "output.file.path";

interface SettingItem {
  id: string;
  section: SettingSection;
  title: string;
  description: string;
  keywords: string[];
  controlKind: ControlKind;
  affordance: string;
  interactive: boolean;
  readOnlyReason?: string;
  value: () => string;
  isOn?: () => boolean;
  toggle?: () => void;
  setToggleValue?: (value: boolean) => void;
  activate?: () => void;
}

interface SettingsDialogData {
  selectedSettingId?: string;
  filterQuery?: string;
}

const SECTION_ORDER: SettingSection[] = ["Capture", "Model", "Output", "Appearance", "Advanced"];

function boolLabel(value: boolean): string {
  return value ? "on" : "off";
}

function withFallback(value: string | number | null | undefined, fallback = "-"): string {
  if (value === null || value === undefined) return fallback;
  const text = String(value).trim();
  return text.length > 0 ? text : fallback;
}

function isPrintableKey(key: KeyEvent): boolean {
  if (key.ctrl || key.meta || key.option) return false;
  return key.name.length === 1;
}

function LegendHint(props: { keys: string; label: string; danger?: boolean }): JSX.Element {
  const { colors } = useTheme();

  return (
    <box flexDirection="row" alignItems="center" gap={1}>
      <box backgroundColor={props.danger ? colors().error : colors().accent} paddingX={1}>
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
  const initialDialogData = (dialog.currentDialog()?.data as SettingsDialogData | undefined) ?? undefined;

  const [selectedIndex, setSelectedIndex] = createSignal(0);
  const [filterQuery, setFilterQuery] = createSignal(initialDialogData?.filterQuery ?? "");
  const [filterMode, setFilterMode] = createSignal(false);
  const [consumedRestoreSettingId, setConsumedRestoreSettingId] = createSignal<string | null>(null);
  const [settingsScrollVersion, setSettingsScrollVersion] = createSignal(0);
  const [scrollRetryCount, setScrollRetryCount] = createSignal(0);
  let scrollRetryTimer: ReturnType<typeof setTimeout> | null = null;
  let settingsScroll: ScrollBoxRenderable | undefined;

  const dialogData = createMemo(
    () => (dialog.currentDialog()?.data as SettingsDialogData | undefined) ?? undefined,
  );

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
    const activeRuntime = config.config()?.model.runtime ?? "faster-whisper";
    const match = backend.models().find((model) => model.name === selected);
    return match?.variants?.[activeRuntime as "faster-whisper" | "whisper.cpp"]?.installed
      ? selected
      : "none";
  });

  function returnFilterQuery() {
    const query = filterQuery();
    return query.length > 0 ? query : undefined;
  }

  function openSelector(settingId: SelectSettingId, returnSettingId?: string) {
    dialog.openDialog("settings-select", {
      settingId,
      returnToSettings: true,
      returnSettingId: returnSettingId ?? settingId,
      returnFilterQuery: returnFilterQuery(),
    });
  }

  function openEditor(settingId: EditSettingId, returnSettingId?: string) {
    dialog.openDialog("settings-edit", {
      settingId,
      returnToSettings: true,
      returnSettingId: returnSettingId ?? settingId,
      returnFilterQuery: returnFilterQuery(),
    });
  }

  const items = createMemo<SettingItem[]>(() => {
    const cfg = config.config();
    const outputFileEnabled = Boolean(cfg?.output.file.enabled);

    return [
      {
        id: "hotkey.mode",
        section: "Capture",
        title: "Hotkey Mode",
        description: "Push-to-talk or toggle recording mode",
        keywords: ["hotkey", "mode", "ptt", "toggle"],
        controlKind: "toggle",
        affordance: "toggle",
        interactive: true,
        value: () => withFallback(cfg?.hotkey.mode, "ptt"),
        isOn: () => config.hotkeyMode() === "toggle",
        toggle: config.toggleHotkeyMode,
        setToggleValue: (value: boolean) => {
          if ((config.hotkeyMode() === "toggle") !== value) {
            config.toggleHotkeyMode();
          }
        },
      },
      {
        id: "hotkey.key",
        section: "Capture",
        title: "Hotkey Key",
        description: "Global shortcut for recording",
        keywords: ["hotkey", "shortcut", "key"],
        controlKind: "open",
        affordance: "open",
        interactive: true,
        value: () => withFallback(cfg?.hotkey.key),
        activate: () =>
          dialog.openDialog("hotkey", {
            returnToSettings: true,
            returnSettingId: "hotkey.key",
            returnFilterQuery: returnFilterQuery(),
          }),
      },
      {
        id: "recording.noise",
        section: "Capture",
        title: "Noise Suppression",
        description: "RNNoise denoise pass before transcription",
        keywords: ["noise", "rnnoise", "cleanup"],
        controlKind: "toggle",
        affordance: "toggle",
        interactive: true,
        value: () => boolLabel(config.noiseEnabled()),
        isOn: config.noiseEnabled,
        toggle: config.toggleNoise,
        setToggleValue: (value: boolean) => {
          if (config.noiseEnabled() !== value) {
            config.toggleNoise();
          }
        },
      },
      {
        id: "recording.vad",
        section: "Capture",
        title: "Voice Activity Detection",
        description: "Trim silence at the beginning and end",
        keywords: ["vad", "silence", "trim"],
        controlKind: "toggle",
        affordance: "toggle",
        interactive: true,
        value: () => boolLabel(config.vadEnabled()),
        isOn: config.vadEnabled,
        toggle: config.toggleVad,
        setToggleValue: (value: boolean) => {
          if (config.vadEnabled() !== value) {
            config.toggleVad();
          }
        },
      },
      {
        id: "audio.sample_rate",
        section: "Capture",
        title: "Sample Rate",
        description: "Audio capture sample rate",
        keywords: ["sample", "hz", "audio", "capture"],
        controlKind: "select",
        affordance: "select",
        interactive: true,
        value: () => withFallback(cfg?.audio.sample_rate),
        activate: () => openSelector("audio.sample_rate"),
      },
      {
        id: "vad.aggressiveness",
        section: "Capture",
        title: "VAD Aggressiveness",
        description: "VAD sensitivity level",
        keywords: ["vad", "aggressive", "sensitivity"],
        controlKind: "select",
        affordance: "select",
        interactive: true,
        value: () => withFallback(cfg?.vad.aggressiveness),
        activate: () => openSelector("vad.aggressiveness"),
      },
      {
        id: "model.name",
        section: "Model",
        title: "Selected Model",
        description: "Open model manager",
        keywords: ["model", "manager", "whisper"],
        controlKind: "open",
        affordance: "open",
        interactive: true,
        value: () => selectedInstalledModelName(),
        activate: () =>
          dialog.openDialog("model-manager", {
            returnToSettings: true,
            returnSettingId: "model.name",
            returnFilterQuery: returnFilterQuery(),
          }),
      },
      {
        id: "model.runtime",
        section: "Model",
        title: "Runtime",
        description: "Choose model runtime",
        keywords: ["runtime", "faster-whisper", "whisper.cpp"],
        controlKind: "select",
        affordance: "select",
        interactive: true,
        value: () => withFallback(cfg?.model.runtime, "faster-whisper"),
        activate: () => openSelector("model.runtime"),
      },
      {
        id: "model.device",
        section: "Model",
        title: "Device",
        description: "Choose runtime device",
        keywords: ["device", "cpu", "cuda", "mps"],
        controlKind: "select",
        affordance: "select",
        interactive: true,
        value: () => formatDeviceLabel(cfg?.model.device),
        activate: () => openSelector("model.device"),
      },
      {
        id: "model.compute",
        section: "Model",
        title: "Compute Type",
        description: "Choose quantization profile",
        keywords: ["compute", "int8", "float16", "float32"],
        controlKind: "select",
        affordance: "select",
        interactive: true,
        value: () => withFallback(cfg?.model.compute_type),
        activate: () => openSelector("model.compute"),
      },
      {
        id: "model.language",
        section: "Model",
        title: "Language",
        description: "Search and choose language",
        keywords: ["language", "locale", "auto"],
        controlKind: "select",
        affordance: "select",
        interactive: true,
        value: () => withFallback(cfg?.model.language, "auto"),
        activate: () => openSelector("model.language"),
      },
      {
        id: "model.path",
        section: "Model",
        title: "Local Model Path",
        description: "Optional local model override",
        keywords: ["path", "filesystem", "cache", "model"],
        controlKind: "edit",
        affordance: "edit",
        interactive: true,
        value: () => withFallback(cfg?.model.path, "default cache"),
        activate: () => openEditor("model.path"),
      },
      {
        id: "recording.autocopy",
        section: "Output",
        title: "Auto Copy",
        description: "Copy transcript text automatically",
        keywords: ["clipboard", "copy", "automatic"],
        controlKind: "toggle",
        affordance: "toggle",
        interactive: true,
        value: () => boolLabel(config.autoCopy()),
        isOn: config.autoCopy,
        toggle: config.toggleAutoCopy,
        setToggleValue: (value: boolean) => {
          if (config.autoCopy() !== value) {
            config.toggleAutoCopy();
          }
        },
      },
      {
        id: "recording.autopaste",
        section: "Output",
        title: "Auto Paste",
        description: "Paste transcript text into focused app",
        keywords: ["clipboard", "paste", "automatic"],
        controlKind: "toggle",
        affordance: "toggle",
        interactive: true,
        value: () => boolLabel(config.autoPaste()),
        isOn: config.autoPaste,
        toggle: config.toggleAutoPaste,
        setToggleValue: (value: boolean) => {
          if (config.autoPaste() !== value) {
            config.toggleAutoPaste();
          }
        },
      },
      {
        id: "recording.autorevertclipboard",
        section: "Output",
        title: "Auto Revert Clipboard",
        description: "Restore previous clipboard after auto-paste",
        keywords: ["clipboard", "paste", "restore", "automatic"],
        controlKind: "toggle",
        affordance: "toggle",
        interactive: true,
        value: () => boolLabel(config.autoRevertClipboard()),
        isOn: config.autoRevertClipboard,
        toggle: config.toggleAutoRevertClipboard,
        setToggleValue: (value: boolean) => {
          if (config.autoRevertClipboard() !== value) {
            config.toggleAutoRevertClipboard();
          }
        },
      },
      {
        id: "output.clipboard",
        section: "Output",
        title: "Clipboard Output",
        description: "Write transcript output to clipboard",
        keywords: ["output", "clipboard", "copy"],
        controlKind: "toggle",
        affordance: "toggle",
        interactive: true,
        value: () => boolLabel(config.outputClipboard()),
        isOn: config.outputClipboard,
        toggle: config.toggleOutputClipboard,
        setToggleValue: (value: boolean) => {
          if (config.outputClipboard() !== value) {
            config.toggleOutputClipboard();
          }
        },
      },
      {
        id: "output.file.enabled",
        section: "Output",
        title: "File Output Enabled",
        description: "Append transcripts to file",
        keywords: ["output", "file", "write"],
        controlKind: "toggle",
        affordance: "toggle",
        interactive: true,
        value: () => boolLabel(config.outputFileEnabled()),
        isOn: config.outputFileEnabled,
        toggle: config.toggleOutputFileEnabled,
        setToggleValue: (value: boolean) => {
          if (config.outputFileEnabled() !== value) {
            config.toggleOutputFileEnabled();
          }
        },
      },
      {
        id: "output.file.path",
        section: "Output",
        title: "Output File Path",
        description: "Destination path for file output",
        keywords: ["output", "file", "path"],
        controlKind: "edit",
        affordance: outputFileEnabled ? "edit" : "locked",
        interactive: outputFileEnabled,
        readOnlyReason: outputFileEnabled ? undefined : "Enable File Output first",
        value: () => withFallback(cfg?.output.file.path),
        activate: () => openEditor("output.file.path"),
      },
      {
        id: "ui.theme",
        section: "Appearance",
        title: "Theme",
        description: "Choose UI theme",
        keywords: ["theme", "appearance", "color", "palette"],
        controlKind: "open",
        affordance: "open",
        interactive: true,
        value: () => withFallback(theme().label),
        activate: () =>
          dialog.openDialog("theme-picker", {
            returnToSettings: true,
            returnSettingId: "ui.theme",
            returnFilterQuery: returnFilterQuery(),
          }),
      },
      {
        id: "audio.noise.level",
        section: "Advanced",
        title: "Noise Level",
        description: "RNNoise suppression level",
        keywords: ["noise", "level", "rnnoise"],
        controlKind: "read-only",
        affordance: "read-only",
        interactive: false,
        readOnlyReason: "Displayed for diagnostics; runtime tuning is not wired",
        value: () => withFallback(cfg?.audio.noise_suppression.level),
      },
      {
        id: "vad.min_speech",
        section: "Advanced",
        title: "VAD Min Speech ms",
        description: "Minimum speech segment",
        keywords: ["vad", "speech", "timing"],
        controlKind: "read-only",
        affordance: "read-only",
        interactive: false,
        readOnlyReason: "Displayed for diagnostics; runtime tuning is not wired",
        value: () => withFallback(cfg?.vad.min_speech_ms),
      },
      {
        id: "vad.max_silence",
        section: "Advanced",
        title: "VAD Max Silence ms",
        description: "Silence allowed before split",
        keywords: ["vad", "silence", "timing"],
        controlKind: "read-only",
        affordance: "read-only",
        interactive: false,
        readOnlyReason: "Displayed for diagnostics; runtime tuning is not wired",
        value: () => withFallback(cfg?.vad.max_silence_ms),
      },
      {
        id: "bridge.host",
        section: "Advanced",
        title: "Bridge Host",
        description: "WebSocket bridge host",
        keywords: ["bridge", "host", "network"],
        controlKind: "read-only",
        affordance: "read-only",
        interactive: false,
        readOnlyReason: "Diagnostics only",
        value: () => withFallback(cfg?.bridge.host),
      },
      {
        id: "bridge.port",
        section: "Advanced",
        title: "Bridge Port",
        description: "WebSocket bridge port",
        keywords: ["bridge", "port", "network"],
        controlKind: "read-only",
        affordance: "read-only",
        interactive: false,
        readOnlyReason: "Diagnostics only",
        value: () => withFallback(cfg?.bridge.port),
      },
      {
        id: "system.config_path",
        section: "Advanced",
        title: "Config Path",
        description: "Copy config path to clipboard",
        keywords: ["config", "path", "toml", "copy"],
        controlKind: "open",
        affordance: "copy",
        interactive: true,
        value: () => configPath(),
        activate: () => backend.send({ type: "copy_text", text: configPath() }),
      },
    ];
  });

  const filteredItems = createMemo(() => {
    const needle = filterQuery().trim().toLowerCase();
    if (!needle) return items();

    return items().filter((item) => {
      const haystack = [
        item.id,
        item.section,
        item.title,
        item.description,
        item.keywords.join(" "),
        item.value(),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
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
  const requestedRestoreSettingId = createMemo(
    () => dialogData()?.selectedSettingId?.trim() || null,
  );

  const selectedItem = createMemo(() => {
    const list = flatItems();
    if (list.length === 0) return null;
    const requested = requestedRestoreSettingId();
    if (requested && consumedRestoreSettingId() !== requested) {
      const requestedItem = list.find((item) => item.id === requested);
      if (requestedItem) return requestedItem;
    }
    return list[selectedIndex()] ?? list[0] ?? null;
  });

  createEffect(() => {
    if (dialog.currentDialog()?.type !== "settings") {
      setConsumedRestoreSettingId(null);
      setScrollRetryCount(0);
      if (scrollRetryTimer) {
        clearTimeout(scrollRetryTimer);
        scrollRetryTimer = null;
      }
      return;
    }
    const requested = requestedRestoreSettingId();
    if (!requested) return;
    if (consumedRestoreSettingId() === requested) return;

    const idx = flatItems().findIndex((item) => item.id === requested);
    if (idx >= 0) {
      setSelectedIndex(idx);
      setConsumedRestoreSettingId(requested);
    }
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
    settingsScrollVersion();
    const active = selectedItem();
    if (!active) return;
    if (dialog.currentDialog()?.type !== "settings") return;
    if (!settingsScroll || settingsScroll.isDestroyed) return;

    const offset = itemScrollOffsets().get(active.id);
    if (offset === undefined) return;

    const rowTop = offset;
    const rowBottom = rowTop + 1;
    const viewportHeight = settingsScroll.viewport.height;
    if (viewportHeight <= 0) {
      if (scrollRetryCount() < 30 && !scrollRetryTimer) {
        setScrollRetryCount((count) => count + 1);
        scrollRetryTimer = setTimeout(() => {
          scrollRetryTimer = null;
          setSettingsScrollVersion((version) => version + 1);
        }, 16);
      }
      return;
    }
    if (scrollRetryCount() !== 0) setScrollRetryCount(0);

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

  onCleanup(() => {
    if (!scrollRetryTimer) return;
    clearTimeout(scrollRetryTimer);
    scrollRetryTimer = null;
  });

  function moveSelection(delta: number) {
    const list = flatItems();
    if (list.length === 0) return;

    let next = selectedIndex() + delta;
    if (next < 0) next = list.length - 1;
    if (next >= list.length) next = 0;
    setSelectedIndex(next);
  }

  function activateItem(item: SettingItem | null) {
    if (!item || !item.interactive) return;

    if (item.controlKind === "toggle") {
      item.toggle?.();
      return;
    }

    item.activate?.();
  }

  function dismissSettings() {
    if (filterMode()) {
      setFilterMode(false);
      if (filterQuery().length > 0) {
        setFilterQuery("");
      }
      return;
    }

    if (filterQuery().length > 0) {
      setFilterQuery("");
      return;
    }

    dialog.closeDialog();
  }

  const unregisterDismissHandler = dialog.registerDismissHandler("settings", dismissSettings);
  onCleanup(unregisterDismissHandler);

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "settings") return;
    if (key.eventType === "release") return;

    if (filterMode()) {
      switch (key.name) {
        case "up":
          key.preventDefault();
          setFilterMode(false);
          moveSelection(-1);
          return;
        case "down":
          key.preventDefault();
          setFilterMode(false);
          moveSelection(1);
          return;
        case "escape":
        case "q":
          key.preventDefault();
          dismissSettings();
          return;
        case "return":
        case "enter":
          key.preventDefault();
          setFilterMode(false);
          activateItem(selectedItem());
          return;
        case "backspace":
          key.preventDefault();
          setFilterQuery((prev) => prev.slice(0, -1));
          return;
        case "space":
          key.preventDefault();
          setFilterQuery((prev) => `${prev} `);
          return;
        default:
          if (!isPrintableKey(key)) return;
          key.preventDefault();
          setFilterQuery((prev) => `${prev}${key.name}`);
          return;
      }
    }

    switch (key.name) {
      case "/":
        key.preventDefault();
        setFilterMode(true);
        return;
      case "escape":
      case "q":
        key.preventDefault();
        dismissSettings();
        return;
      case "up":
      case "k":
        key.preventDefault();
        moveSelection(-1);
        return;
      case "down":
      case "j":
        key.preventDefault();
        moveSelection(1);
        return;
      case "left": {
        const item = selectedItem();
        if (item?.controlKind === "toggle" && item.setToggleValue) {
          key.preventDefault();
          item.setToggleValue(false);
        }
        return;
      }
      case "right": {
        const item = selectedItem();
        if (item?.controlKind === "toggle" && item.setToggleValue) {
          key.preventDefault();
          item.setToggleValue(true);
        }
        return;
      }
      case "space":
      case "return":
      case "enter":
        key.preventDefault();
        activateItem(selectedItem());
        return;
      default:
        return;
    }
  });

  const valueColor = (item: SettingItem, active: boolean) => {
    if (item.controlKind === "toggle") {
      if (item.isOn?.()) return colors().success;
      return active ? colors().textMuted : colors().textDim;
    }

    if (!item.interactive) {
      return active ? colors().textMuted : colors().textDim;
    }

    return active ? colors().text : colors().accent;
  };

  const descriptionText = (item: SettingItem) => {
    if (item.readOnlyReason) {
      return `${item.description} (${item.readOnlyReason})`;
    }
    return item.description;
  };

  return (
    <box
      flexDirection="column"
      width={94}
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
              <span style={{ fg: colors().textMuted }}>task-first controls</span>
            </text>
            <box backgroundColor={colors().error} paddingX={1} onMouseUp={dismissSettings}>
              <text>
                <span style={{ fg: colors().selectedText }}>esc/q</span>
              </text>
            </box>
          </box>
        </box>
        <box flexDirection="row" width="100%" marginTop={0}>
          <box width={3} borderStyle="single" border={["bottom"]} borderColor={colors().accent} />
          <box flexGrow={1} borderStyle="single" border={["bottom"]} borderColor={colors().borderSubtle} />
        </box>
      </box>

      <box paddingX={3} paddingTop={1} flexShrink={0}>
        <text>
          <span style={{ fg: colors().textDim }}>filter: </span>
          <span style={{ fg: colors().text }}>{filterQuery() || "all settings"}</span>
          <Show when={filterMode()}>
            <span style={{ fg: colors().accent }}> |</span>
          </Show>
        </text>
      </box>

      <scrollbox
        flexGrow={1}
        flexShrink={1}
        paddingTop={1}
        ref={(r: ScrollBoxRenderable) => {
          settingsScroll = r;
          setSettingsScrollVersion((version) => version + 1);
        }}
      >
        <Show
          when={groupedItems().length > 0}
          fallback={
            <box paddingX={3} paddingY={1}>
              <text fg={colors().textMuted}>
                {filterQuery() ? "No settings match this filter." : "No settings available."}
              </text>
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
                          flexDirection="row"
                          paddingRight={1}
                          backgroundColor={isActive() ? colors().backgroundElement : undefined}
                          onMouseUp={() => {
                            const idx = flatItems().findIndex((entry) => entry.id === item.id);
                            if (idx >= 0) setSelectedIndex(idx);
                            activateItem(item);
                          }}
                        >
                          <box
                            width={1}
                            backgroundColor={isActive() ? colors().accent : undefined}
                          />
                          <box paddingLeft={2} flexDirection="row" width="100%" justifyContent="space-between" gap={2}>
                            <box flexDirection="column" flexGrow={1}>
                              <text>
                                <span style={{ fg: colors().text }}>{item.title}</span>
                              </text>
                              <text>
                                <span style={{ fg: item.readOnlyReason ? colors().warning : colors().textMuted }}>
                                  {descriptionText(item)}
                                </span>
                              </text>
                            </box>
                            <box flexDirection="column" alignItems="flex-end">
                              <text>
                                <span style={{ fg: valueColor(item, isActive()) }}>{item.value()}</span>
                              </text>
                              <text>
                                <span style={{ fg: item.interactive ? colors().textDim : colors().warning }}>
                                  {item.affordance}
                                </span>
                              </text>
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
          <LegendHint keys="↑/↓ j/k" label="navigate" />
          <LegendHint keys="enter/space" label="activate" />
          <LegendHint keys="←/→" label="toggle off/on" />
          <LegendHint keys="/" label="filter" />
          <Show when={filterQuery().length > 0}>
            <LegendHint keys="esc/q" label="clear filter" danger />
          </Show>
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
