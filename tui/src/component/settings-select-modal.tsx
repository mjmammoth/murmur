import { createEffect, createMemo, createSignal, For, Show, type JSX } from "solid-js";
import { useKeyHandler, useTerminalDimensions } from "@opentui/solid";
import type { KeyEvent, ScrollBoxRenderable } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useDialog } from "../context/dialog";
import { useBackend } from "../context/backend";
import { useConfig } from "../context/config";

type SelectSettingId = "model.backend" | "model.device" | "model.compute" | "model.language";

interface SettingsSelectDialogData {
  settingId: SelectSettingId;
  returnToSettings?: boolean;
}

interface SelectOption {
  value: string | null;
  label: string;
  description: string;
  disabled?: boolean;
  reason?: string | null;
}

const LANGUAGE_OPTIONS: SelectOption[] = [
  { value: null, label: "Auto detect", description: "Use Whisper language detection" },
  { value: "en", label: "English", description: "en" },
  { value: "es", label: "Spanish", description: "es" },
  { value: "fr", label: "French", description: "fr" },
  { value: "de", label: "German", description: "de" },
  { value: "it", label: "Italian", description: "it" },
  { value: "pt", label: "Portuguese", description: "pt" },
  { value: "nl", label: "Dutch", description: "nl" },
  { value: "pl", label: "Polish", description: "pl" },
  { value: "cs", label: "Czech", description: "cs" },
  { value: "sv", label: "Swedish", description: "sv" },
  { value: "fi", label: "Finnish", description: "fi" },
  { value: "da", label: "Danish", description: "da" },
  { value: "no", label: "Norwegian", description: "no" },
  { value: "tr", label: "Turkish", description: "tr" },
  { value: "el", label: "Greek", description: "el" },
  { value: "ru", label: "Russian", description: "ru" },
  { value: "uk", label: "Ukrainian", description: "uk" },
  { value: "ro", label: "Romanian", description: "ro" },
  { value: "bg", label: "Bulgarian", description: "bg" },
  { value: "hu", label: "Hungarian", description: "hu" },
  { value: "ar", label: "Arabic", description: "ar" },
  { value: "he", label: "Hebrew", description: "he" },
  { value: "fa", label: "Persian", description: "fa" },
  { value: "hi", label: "Hindi", description: "hi" },
  { value: "ur", label: "Urdu", description: "ur" },
  { value: "bn", label: "Bengali", description: "bn" },
  { value: "ta", label: "Tamil", description: "ta" },
  { value: "te", label: "Telugu", description: "te" },
  { value: "kn", label: "Kannada", description: "kn" },
  { value: "ml", label: "Malayalam", description: "ml" },
  { value: "mr", label: "Marathi", description: "mr" },
  { value: "gu", label: "Gujarati", description: "gu" },
  { value: "pa", label: "Punjabi", description: "pa" },
  { value: "ja", label: "Japanese", description: "ja" },
  { value: "ko", label: "Korean", description: "ko" },
  { value: "zh", label: "Chinese", description: "zh" },
  { value: "th", label: "Thai", description: "th" },
  { value: "vi", label: "Vietnamese", description: "vi" },
  { value: "id", label: "Indonesian", description: "id" },
  { value: "ms", label: "Malay", description: "ms" },
  { value: "tl", label: "Tagalog", description: "tl" },
  { value: "sw", label: "Swahili", description: "sw" },
  { value: "af", label: "Afrikaans", description: "af" },
  { value: "is", label: "Icelandic", description: "is" },
  { value: "ga", label: "Irish", description: "ga" },
  { value: "cy", label: "Welsh", description: "cy" },
];

function normalizeValue(value: string | null | undefined): string {
  return value ?? "";
}

function optionId(value: string | null | undefined): string {
  return value ?? "__auto__";
}

function isPrintableKey(key: KeyEvent): boolean {
  if (key.ctrl || key.meta || key.option) return false;
  return key.name.length === 1;
}

export function SettingsSelectModal(): JSX.Element {
  const { colors } = useTheme();
  const dialog = useDialog();
  const backend = useBackend();
  const config = useConfig();
  const terminal = useTerminalDimensions();

  const [selectedIndex, setSelectedIndex] = createSignal(0);
  const [query, setQuery] = createSignal("");
  let optionScroll: ScrollBoxRenderable | undefined;

  const dialogData = createMemo(
    () => (dialog.currentDialog()?.data as SettingsSelectDialogData | undefined) ?? null,
  );
  const settingId = createMemo<SelectSettingId | null>(() => dialogData()?.settingId ?? null);
  const returnToSettings = createMemo(() => Boolean(dialogData()?.returnToSettings));
  const isLanguagePicker = createMemo(() => settingId() === "model.language");
  const runtimeModel = createMemo(() => config.config()?.runtime?.model);

  const currentValue = createMemo(() => {
    const model = config.config()?.model;
    switch (settingId()) {
      case "model.backend":
        return model?.backend ?? "faster-whisper";
      case "model.device":
        return model?.device ?? "cpu";
      case "model.compute":
        return model?.compute_type ?? "int8";
      case "model.language":
        return model?.language ?? null;
      default:
        return null;
    }
  });

  const title = createMemo(() => {
    switch (settingId()) {
      case "model.backend":
        return "Model Backend";
      case "model.device":
        return "Model Device";
      case "model.compute":
        return "Compute Type";
      case "model.language":
        return "Model Language";
      default:
        return "Select Option";
    }
  });

  const subtitle = createMemo(() => {
    switch (settingId()) {
      case "model.backend":
        return "choose transcription engine";
      case "model.device":
        return "choose runtime backend";
      case "model.compute":
        return "choose quantization profile";
      case "model.language":
        return "type to filter languages";
      default:
        return "choose value";
    }
  });

  const backendOptions = createMemo<SelectOption[]>(() => {
    const backends = runtimeModel()?.backends ?? {};
    return [
      {
        value: "faster-whisper",
        label: "faster-whisper",
        description: "CTranslate2 backend",
        disabled: backends["faster-whisper"] ? !backends["faster-whisper"].enabled : false,
        reason: backends["faster-whisper"]?.reason,
      },
      {
        value: "whisper.cpp",
        label: "whisper.cpp",
        description: "CLI backend (Metal capable)",
        disabled: backends["whisper.cpp"] ? !backends["whisper.cpp"].enabled : false,
        reason: backends["whisper.cpp"]?.reason,
      },
    ];
  });

  const deviceOptions = createMemo<SelectOption[]>(() => [
    {
      value: "cpu",
      label: "CPU",
      description: "Most compatible",
      disabled: runtimeModel()?.devices?.cpu ? !runtimeModel()!.devices.cpu.enabled : false,
      reason: runtimeModel()?.devices?.cpu?.reason,
    },
    {
      value: "cuda",
      label: "CUDA",
      description: "NVIDIA GPU acceleration",
      disabled: runtimeModel()?.devices?.cuda ? !runtimeModel()!.devices.cuda.enabled : false,
      reason: runtimeModel()?.devices?.cuda?.reason,
    },
    {
      value: "mps",
      label: "MPS",
      description: "Apple GPU backend",
      disabled: runtimeModel()?.devices?.mps ? !runtimeModel()!.devices.mps.enabled : false,
      reason: runtimeModel()?.devices?.mps?.reason,
    },
  ]);

  const computeOptions = createMemo<SelectOption[]>(() => {
    const device = (config.config()?.model.device ?? "cpu").toLowerCase();
    const deviceState = runtimeModel()?.devices?.[device];
    const supportedCompute = runtimeModel()?.compute_types_by_device?.[device] ?? [];
    const supportedSet = new Set(supportedCompute.map((item) => item.toLowerCase()));

    if (supportedSet.size === 1 && supportedSet.has("default")) {
      return [
        {
          value: "default",
          label: "default",
          description: "Backend-managed compute profile",
          disabled: deviceState ? !deviceState.enabled : false,
          reason: deviceState?.reason,
        },
      ];
    }

    const base =
      device === "cuda"
        ? [
            { value: "int8", label: "int8", description: "Balanced speed and quality" },
            { value: "float16", label: "float16", description: "GPU half precision" },
            { value: "float32", label: "float32", description: "Highest precision" },
            { value: "int8_float32", label: "int8_float32", description: "Mixed precision" },
            { value: "int8_float16", label: "int8_float16", description: "Mixed precision" },
          ]
        : [
            { value: "int8", label: "int8", description: "Recommended on CPU" },
            { value: "float32", label: "float32", description: "Higher precision, slower" },
            { value: "int8_float32", label: "int8_float32", description: "Mixed precision" },
            { value: "float16", label: "float16", description: "Will auto-fallback on CPU" },
            { value: "int8_float16", label: "int8_float16", description: "Will auto-fallback on CPU" },
          ];

    const withState = base.map((option) => {
      if (deviceState && !deviceState.enabled) {
        return { ...option, disabled: true, reason: deviceState.reason ?? "Device unavailable" };
      }

      if (device === "cpu" && (option.value === "float16" || option.value === "int8_float16")) {
        return {
          ...option,
          disabled: true,
          reason: "CPU mode auto-falls back to int8 for this type",
        };
      }

      if (supportedSet.size > 0 && !supportedSet.has(option.value.toLowerCase())) {
        return {
          ...option,
          disabled: true,
          reason: `Not supported on ${device.toUpperCase()}`,
        };
      }

      return option;
    });

    const current = normalizeValue(currentValue() as string | null);
    if (!current) return withState;
    if (withState.some((option) => option.value === current)) return withState;

    return [{ value: current, label: current, description: "Current" }, ...withState];
  });

  const allOptions = createMemo<SelectOption[]>(() => {
    switch (settingId()) {
      case "model.backend":
        return backendOptions();
      case "model.device":
        return deviceOptions();
      case "model.compute":
        return computeOptions();
      case "model.language":
        return LANGUAGE_OPTIONS;
      default:
        return [];
    }
  });

  const filteredOptions = createMemo(() => {
    if (!isLanguagePicker()) return allOptions();
    const needle = query().trim().toLowerCase();
    if (!needle) return allOptions();

    return allOptions().filter((option) => {
      const haystack = `${option.label} ${option.description} ${option.value ?? "auto"}`.toLowerCase();
      return haystack.includes(needle);
    });
  });

  const selectedOption = createMemo(() => {
    const options = filteredOptions();
    if (options.length === 0) return null;
    return options[selectedIndex()] ?? options[0] ?? null;
  });

  function closeModal() {
    if (returnToSettings()) {
      dialog.openDialog("settings");
      return;
    }
    dialog.closeDialog();
  }

  function moveSelection(delta: number) {
    const options = filteredOptions();
    if (options.length === 0) return;
    let next = selectedIndex();

    for (let i = 0; i < options.length; i++) {
      next += delta;
      if (next < 0) next = options.length - 1;
      if (next >= options.length) next = 0;
      if (!options[next]?.disabled) break;
    }

    setSelectedIndex(next);
  }

  function scrollSelectedIntoView(center = false) {
    if (!optionScroll || optionScroll.isDestroyed) return;
    const selected = selectedOption();
    if (!selected) return;

    const target = optionScroll.getChildren().find((child) => child.id === optionId(selected.value));
    if (!target) return;

    const top = target.y - optionScroll.y;
    const bottom = top + Math.max(1, target.height) - 1;

    if (center) {
      const centerOffset = Math.floor((optionScroll.height - target.height) / 2);
      optionScroll.scrollBy(top - centerOffset);
      return;
    }

    if (bottom >= optionScroll.height) {
      optionScroll.scrollBy(bottom - optionScroll.height + 1);
      return;
    }

    if (top < 0) {
      optionScroll.scrollBy(top);
      if (filteredOptions()[0]?.value === selected.value) {
        optionScroll.scrollTo(0);
      }
    }
  }

  function applyOption(option: SelectOption | null) {
    if (!option) return;
    if (option.disabled) return;

    switch (settingId()) {
      case "model.backend":
        backend.send({ type: "set_model_backend", backend: option.value ?? "faster-whisper" });
        break;
      case "model.device":
        backend.send({ type: "set_model_device", device: option.value ?? "cpu" });
        break;
      case "model.compute":
        backend.send({ type: "set_model_compute_type", compute_type: option.value ?? "int8" });
        break;
      case "model.language":
        backend.send({ type: "set_model_language", language: option.value });
        break;
      default:
        return;
    }

    closeModal();
  }

  function applySelection() {
    applyOption(selectedOption());
  }

  createEffect(() => {
    const options = filteredOptions();
    if (options.length === 0) {
      setSelectedIndex(0);
      return;
    }
    if (selectedIndex() >= options.length) {
      setSelectedIndex(options.length - 1);
    }
  });

  createEffect(() => {
    const options = filteredOptions();
    if (options.length === 0) return;
    const current = normalizeValue(currentValue() as string | null);
    const index = options.findIndex((option) => normalizeValue(option.value) === current);
    if (index >= 0) setSelectedIndex(index);
    setTimeout(() => {
      scrollSelectedIntoView(true);
    }, 0);
  });

  createEffect(() => {
    selectedOption();
    setTimeout(() => {
      scrollSelectedIntoView();
    }, 0);
  });

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "settings-select") return;
    if (key.eventType === "release") return;

    switch (key.name) {
      case "escape":
        key.preventDefault();
        closeModal();
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
      case "return":
      case "enter":
        key.preventDefault();
        applySelection();
        return;
      case "backspace":
        if (!isLanguagePicker()) return;
        key.preventDefault();
        setQuery((prev) => prev.slice(0, -1));
        return;
      case "space":
        if (!isLanguagePicker()) return;
        key.preventDefault();
        setQuery((prev) => `${prev} `);
        return;
      default:
        if (!isLanguagePicker() || !isPrintableKey(key)) return;
        key.preventDefault();
        setQuery((prev) => `${prev}${key.name}`);
    }
  });

  const modalWidth = createMemo(() => {
    const maxWidth = Math.max(52, terminal().width - 8);
    const preferred = Math.floor(terminal().width * 0.6);
    return Math.max(52, Math.min(preferred, maxWidth));
  });

  const modalHeight = createMemo(() => {
    const maxHeight = Math.max(12, terminal().height - 6);
    const preferred = Math.floor(terminal().height * 0.7);
    return Math.max(12, Math.min(preferred, maxHeight));
  });

  return (
    <box
      flexDirection="column"
      width={modalWidth()}
      height={modalHeight()}
      backgroundColor={colors().backgroundPanel}
      paddingY={1}
    >
      <box paddingX={3} paddingTop={1} paddingBottom={0} flexDirection="column" flexShrink={0}>
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>{title()}</span>
          </text>
          <box flexDirection="row" alignItems="center" gap={2}>
            <text>
              <span style={{ fg: colors().textMuted }}>{subtitle()}</span>
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

      <Show when={isLanguagePicker()}>
        <box paddingX={3} paddingTop={1} flexShrink={0}>
          <text>
            <span style={{ fg: colors().textDim }}>filter: </span>
            <span style={{ fg: colors().text }}>{query() || "all languages"}</span>
          </text>
        </box>
      </Show>

      <scrollbox
        flexGrow={1}
        flexShrink={1}
        paddingTop={1}
        ref={(r: ScrollBoxRenderable) => {
          optionScroll = r;
        }}
      >
        <Show
          when={filteredOptions().length > 0}
          fallback={
            <box paddingX={3} paddingY={1}>
              <text>
                <span style={{ fg: colors().textMuted }}>No options match this filter.</span>
              </text>
            </box>
          }
        >
          <For each={filteredOptions()}>
            {(option) => {
              const isActive = () => normalizeValue(option.value) === normalizeValue(selectedOption()?.value);
              const isCurrent = () => normalizeValue(option.value) === normalizeValue(currentValue() as string | null);

              return (
                <box
                  id={optionId(option.value)}
                  flexDirection="row"
                  paddingRight={1}
                  backgroundColor={isActive() ? colors().backgroundElement : undefined}
                  onMouseUp={() => {
                    if (option.disabled) return;
                    const index = filteredOptions().findIndex(
                      (entry) => normalizeValue(entry.value) === normalizeValue(option.value),
                    );
                    if (index >= 0) setSelectedIndex(index);
                    applyOption(option);
                  }}
                >
                  <box width={1} backgroundColor={isActive() ? colors().secondary : undefined} />
                  <box paddingLeft={2} flexDirection="row" width="100%" justifyContent="space-between" gap={2}>
                    <box flexDirection="column" flexGrow={1}>
                      <text>
                        <span style={{ fg: option.disabled ? colors().textDim : colors().text }}>
                          {option.label}
                        </span>
                      </text>
                      <text>
                        <span style={{ fg: option.disabled ? colors().warning : colors().textMuted }}>
                          {option.disabled && option.reason ? option.reason : option.description}
                        </span>
                      </text>
                    </box>
                    <box alignItems="flex-end">
                      <text>
                        <span
                          style={{
                            fg: isCurrent()
                              ? option.disabled
                                ? colors().warning
                                : colors().success
                              : option.disabled
                                ? colors().textDim
                                : colors().textDim,
                          }}
                        >
                          {isCurrent() ? "current" : option.disabled ? "disabled" : ""}
                        </span>
                      </text>
                    </box>
                  </box>
                </box>
              );
            }}
          </For>
        </Show>
      </scrollbox>

      <box flexShrink={0} paddingX={3} paddingTop={1}>
        <box flexDirection="row" gap={2} alignItems="center">
          <text>
            <span style={{ fg: colors().textMuted }}>↑/↓ navigate</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>enter apply</span>
          </text>
          <Show when={isLanguagePicker()}>
            <text>
              <span style={{ fg: colors().textMuted }}>type filter</span>
            </text>
          </Show>
        </box>
      </box>
    </box>
  );
}
