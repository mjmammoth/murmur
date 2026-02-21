import {
  createSignal,
  createMemo,
  createEffect,
  onCleanup,
  on,
  For,
  Show,
  type JSX,
} from "solid-js";
import { useKeyHandler, useTerminalDimensions } from "@opentui/solid";
import type { KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useBackend, type CapabilitiesResponse } from "../context/backend";
import { useDialog } from "../context/dialog";
import { useSpinnerFrame } from "./spinner";
import { formatBytes, formatDeviceLabel } from "../util/format";
import type { RuntimeName, SelectSettingId, WelcomeDialogData } from "../types";

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function CommandHint(props: { keys: string; label: string; onClick?: () => void }): JSX.Element {
  const { colors } = useTheme();
  return (
    <box flexDirection="row" alignItems="center" gap={1} onMouseUp={() => props.onClick?.()}>
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

function SectionTitle(props: { text: string }): JSX.Element {
  const { colors } = useTheme();
  return (
    <text>
      <span style={{ fg: colors().primary, bold: true }}>{props.text}</span>
    </text>
  );
}

function Paragraph(props: { children: string }): JSX.Element {
  const { colors } = useTheme();
  return (
    <text>
      <span style={{ fg: colors().text }}>{props.children}</span>
    </text>
  );
}

function Muted(props: { children: string }): JSX.Element {
  const { colors } = useTheme();
  return (
    <text>
      <span style={{ fg: colors().textMuted }}>{props.children}</span>
    </text>
  );
}

// ---------------------------------------------------------------------------
// Step 1: Welcome
// ---------------------------------------------------------------------------

function WelcomeStep(): JSX.Element {
  const { colors } = useTheme();
  return (
    <box flexDirection="column" gap={1} paddingX={2} paddingY={1} flexShrink={0}>
      <text>
        <span style={{ fg: colors().primary, bold: true }}>Welcome to whisper.local</span>
      </text>
      <Paragraph>
        Local speech-to-text transcription, entirely on your machine.
        No data leaves your computer. Audio is captured, transcribed
        by an AI model running locally, and the text is shown here
      </Paragraph>
      <box marginTop={1} flexDirection="column" gap={0}>
        <text>
          <span style={{ fg: colors().accent, bold: true }}>Everything in the UI is clickable.</span>
        </text>
        <Paragraph>Buttons, labels, toggles, status indicators - click them</Paragraph>
        <Paragraph>to interact, or use keyboard shortcuts shown below.</Paragraph>
      </box>
      <box marginTop={1} flexDirection="column" gap={0}>
        <Muted>This walkthrough will help you get set up.</Muted>
        <Muted>You can re-open it anytime by pressing ?</Muted>
      </box>
    </box>
  );
}

// ---------------------------------------------------------------------------
// Step 2: UI Guide
// ---------------------------------------------------------------------------

function UIGuideStep(): JSX.Element {
  const { colors } = useTheme();
  return (
    <box flexDirection="column" gap={1} paddingX={2} paddingY={1} flexShrink={0}>
      <SectionTitle text="How the UI works" />

      <box flexDirection="column" gap={0}>
        <text>
          <span style={{ fg: colors().text }}>Colored letters in labels are </span>
          <span style={{ fg: colors().accent, bold: true }}>hotkeys</span>
          <span style={{ fg: colors().text }}>.</span>
        </text>
        <text>
          <span style={{ fg: colors().text }}>For example, "</span>
          <span style={{ fg: colors().accent, bold: true }}>s</span>
          <span style={{ fg: colors().textDim }}>ettings</span>
          <span style={{ fg: colors().text }}>" means press </span>
          <span style={{ fg: colors().accent, bold: true }}>s</span>
          <span style={{ fg: colors().text }}> to open settings.</span>
        </text>
      </box>

      <box flexDirection="column" gap={0} marginTop={1}>
        <text>
          <span style={{ fg: colors().primary, bold: true }}>Key shortcuts at a glance:</span>
        </text>
        <box flexDirection="row" gap={2}>
          <box flexDirection="column" gap={0}>
            <text>
              <span style={{ fg: colors().accent, bold: true }}>m</span>
              <span style={{ fg: colors().textMuted }}> model manager</span>
            </text>
            <text>
              <span style={{ fg: colors().accent, bold: true }}>q</span>
              <span style={{ fg: colors().textMuted }}> exit app</span>
            </text>
            <text>
              <span style={{ fg: colors().accent, bold: true }}>?</span>
              <span style={{ fg: colors().textMuted }}> open help</span>
            </text>
          </box>
          <box flexDirection="column" gap={0}>
            <text>
              <span style={{ fg: colors().accent, bold: true }}>s</span>
              <span style={{ fg: colors().textMuted }}> settings</span>
            </text>
            <text>
              <span style={{ fg: colors().accent, bold: true }}>h</span>
              <span style={{ fg: colors().textMuted }}> configure hotkey</span>
            </text>
            <text>
              <span style={{ fg: colors().accent, bold: true }}>t</span>
              <span style={{ fg: colors().textMuted }}> theme picker</span>
            </text>
          </box>
        </box>
      </box>

      <box flexDirection="column" gap={0} marginTop={1}>
        <text>
          <span style={{ fg: colors().primary, bold: true }}>Default behavior:</span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>Auto copy: </span>
          <span style={{ fg: colors().accent }}>on</span>
          <span style={{ fg: colors().textMuted }}>, </span>
          <span style={{ fg: colors().textMuted }}>Auto paste: </span>
          <span style={{ fg: colors().accent }}>on</span>
          <span style={{ fg: colors().textMuted }}>, </span>
          <span style={{ fg: colors().textMuted }}>Auto revert clipboard: </span>
          <span style={{ fg: colors().accent }}>on</span>
          <span style={{ fg: colors().textMuted }}>.</span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>Hotkey mode default: </span>
          <span style={{ fg: colors().accent }}>push-to-talk</span>
          <span style={{ fg: colors().textMuted }}> (hold to record).</span>
        </text>
      </box>

      <box flexDirection="column" gap={0} marginTop={1}>
        <text>
          <span style={{ fg: colors().primary, bold: true }}>Global hotkey:</span>
        </text>
        <Paragraph>A system-wide hotkey (default: F3) lets you start/stop</Paragraph>
        <Paragraph>recording from any app. Configure it with h from the main screen.</Paragraph>
        <text>
          <span style={{ fg: colors().textMuted }}>Two modes: </span>
          <span style={{ fg: colors().accent }}>push-to-talk</span>
          <span style={{ fg: colors().textMuted }}> (hold to record) or </span>
          <span style={{ fg: colors().accent }}>toggle</span>
          <span style={{ fg: colors().textMuted }}> (press to start/stop).</span>
        </text>
      </box>
    </box>
  );
}

// ---------------------------------------------------------------------------
// Step 3: Device Detection
// ---------------------------------------------------------------------------

type HardwareSettingField = "runtime" | "device";

function DeviceDetectionStep(props: {
  caps: CapabilitiesResponse | null;
  selectedField: HardwareSettingField;
  onSelectField: (field: HardwareSettingField) => void;
  onOpenSelector: (field: HardwareSettingField) => void;
}): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();

  const loading = () => !props.caps;

  function SuggestionToken(props: { children: string }): JSX.Element {
    return (
      <span style={{ fg: colors().accent, bold: true }}>
        {props.children}
      </span>
    );
  }

  const deviceSummary = () => {
    if (!props.caps) return "Detecting hardware...";
    const rec = props.caps.recommended;
    if (rec.device === "mps") return "Apple Silicon with Metal GPU detected";
    if (rec.device === "cuda") return "NVIDIA GPU with CUDA detected";
    return "CPU-only configuration detected";
  };

  const recommendation = (): JSX.Element => {
    if (!props.caps) {
      return <span style={{ fg: colors().textMuted }}>Detecting recommendation...</span>;
    }
    const rec = props.caps.recommended;
    if (rec.device === "mps") {
      return (
        <>
          <span style={{ fg: colors().textMuted }}>Recommended: </span>
          <SuggestionToken>whisper.cpp</SuggestionToken>
          <span style={{ fg: colors().textMuted }}> with </span>
          <SuggestionToken>Metal</SuggestionToken>
          <span style={{ fg: colors().textMuted }}> for best performance on Mac.</span>
        </>
      );
    }
    if (rec.device === "cuda") {
      return (
        <>
          <span style={{ fg: colors().textMuted }}>Recommended: </span>
          <SuggestionToken>faster-whisper</SuggestionToken>
          <span style={{ fg: colors().textMuted }}> with </span>
          <SuggestionToken>CUDA</SuggestionToken>
          <span style={{ fg: colors().textMuted }}> for GPU-accelerated transcription.</span>
        </>
      );
    }
    return (
      <>
        <span style={{ fg: colors().textMuted }}>Recommended: </span>
        <SuggestionToken>faster-whisper</SuggestionToken>
        <span style={{ fg: colors().textMuted }}> with </span>
        <SuggestionToken>CPU</SuggestionToken>
        <span style={{ fg: colors().textMuted }}>.</span>
        <span style={{ fg: colors().textMuted }}> Consider installing </span>
        <SuggestionToken>whisper.cpp</SuggestionToken>
        <span style={{ fg: colors().textMuted }}> for </span>
        <SuggestionToken>Metal</SuggestionToken>
        <span style={{ fg: colors().textMuted }}> support on Mac.</span>
      </>
    );
  };

  const currentRuntime = () => backend.config()?.model.runtime ?? "-";
  const currentDevice = () => formatDeviceLabel(backend.config()?.model.device);
  const settingRows = createMemo<
    Array<{
      field: HardwareSettingField;
      title: string;
      value: string;
    }>
  >(() => [
    { field: "runtime", title: "Runtime", value: currentRuntime() },
    { field: "device", title: "Device", value: currentDevice() },
  ]);

  return (
    <box flexDirection="column" gap={1} paddingX={2} paddingY={1} flexShrink={0}>
      <SectionTitle text="Hardware detection" />

      <Show when={!loading()} fallback={
        <box flexDirection="column" gap={1}>
          <Muted>Detecting available hardware and compute capabilities...</Muted>
        </box>
      }>
        <text>
          <span style={{ fg: colors().success, bold: true }}>{deviceSummary()}</span>
        </text>
        <text>{recommendation()}</text>

        <box flexDirection="column" gap={0} marginTop={1}>
          <text>
            <span style={{ fg: colors().primary, bold: true }}>Current configuration:</span>
          </text>
          <box flexDirection="column" marginTop={1}>
            <For each={settingRows()}>
              {(row) => {
                const selected = () => props.selectedField === row.field;
                return (
                  <box
                    flexDirection="row"
                    justifyContent="space-between"
                    backgroundColor={selected() ? colors().backgroundElement : undefined}
                    paddingRight={1}
                    onMouseUp={() => {
                      props.onSelectField(row.field);
                      props.onOpenSelector(row.field);
                    }}
                  >
                    <box flexDirection="row">
                      <box
                        width={1}
                        backgroundColor={selected() ? colors().secondary : undefined}
                      />
                      <box paddingLeft={1}>
                        <text>
                          <span style={{ fg: selected() ? colors().text : colors().textMuted }}>
                            {row.title}
                          </span>
                        </text>
                      </box>
                    </box>
                    <box>
                      <text>
                        <span style={{ fg: colors().text }}>{row.value}</span>
                      </text>
                    </box>
                  </box>
                );
              }}
            </For>
          </box>
        </box>

        <box marginTop={1}>
          <text>
            <span style={{ fg: colors().textDim }}>
              Use up/down to pick a field, Enter to edit.
            </span>
          </text>
        </box>
      </Show>
    </box>
  );
}

// ---------------------------------------------------------------------------
// Step 4: Model Download
// ---------------------------------------------------------------------------

const MODEL_DESCRIPTIONS: Record<string, string> = {
  "tiny": "Fastest, least accurate. Good for testing.",
  "base": "Fast, basic accuracy.",
  "small": "Good balance of speed and accuracy. Recommended to start.",
  "medium": "Higher accuracy, slower. Needs more RAM.",
  "large-v2": "High accuracy, significantly slower.",
  "large-v3": "Best accuracy, very large download.",
  "large-v3-turbo": "Near-best accuracy with better speed than large.",
};

function ModelDownloadStep(props: {
  selectedModelIndex: number;
  onSelectModel: (index: number) => void;
}): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const spinnerFrame = useSpinnerFrame();

  const models = () => backend.models();
  const selectedModel = () => models()[props.selectedModelIndex] ?? null;
  const activeRuntime = createMemo<RuntimeName>(
    () => (backend.config()?.model.runtime as RuntimeName | undefined) ?? "faster-whisper",
  );

  const activePulling = createMemo(() => {
    const op = backend.activeModelOp();
    if (!op || op.type !== "pulling") return null;
    return op;
  });

  const selectedModelIsPulling = createMemo(() => {
    const model = selectedModel();
    const pulling = activePulling();
    return Boolean(model && pulling && model.name === pulling.model && pulling.runtime === activeRuntime());
  });

  const selectedModelIsQueued = createMemo(() => {
    const model = selectedModel();
    if (!model) return false;
    return backend.isModelPullQueued(model.name, activeRuntime());
  });

  const selectedModelName = createMemo(() => {
    const configured = backend.config()?.model.name ?? null;
    if (!configured) return null;
    const match = models().find((m) => m.name === configured);
    return match?.variants?.[activeRuntime()]?.installed ? configured : null;
  });

  function handlePullOrSelect() {
    const model = selectedModel();
    const op = backend.activeModelOp();
    const variant = model?.variants?.[activeRuntime()];
    if (!model) return;
    if (selectedModelIsPulling()) {
      const pulling = activePulling();
      backend.cancelModelDownload(model.name, pulling?.runtime ?? activeRuntime());
      return;
    }
    if (selectedModelIsQueued()) {
      backend.cancelModelDownload(model.name, activeRuntime());
      return;
    }
    if (variant?.installed) {
      if (op) return;
      backend.send({ type: "set_selected_model", name: model.name });
      return;
    }
    backend.downloadModel(model.name, activeRuntime());
  }

  return (
    <box flexDirection="column" gap={1} paddingX={2} paddingY={1} height="100%">
      <box flexDirection="column" gap={0} flexShrink={0}>
        <SectionTitle text="Download a model" />
      </box>

      <box flexDirection="column" gap={0} flexShrink={0}>
        <Paragraph>Whisper models are AI speech recognition models that run locally.</Paragraph>
        <Paragraph>Larger models are more accurate but need more disk space and RAM.</Paragraph>
        <text>
          <span style={{ fg: colors().textMuted }}>
            Use up/down arrows to browse, Enter to pull + select.
          </span>
        </text>
      </box>

      <scrollbox flexGrow={1} flexShrink={1}>
        <box flexDirection="column">
          <For each={models()}>
            {(model, index) => {
              const isSelected = () => index() === props.selectedModelIndex;
              const isActive = () => model.name === selectedModelName();
              const variant = () => model.variants[activeRuntime()];
              const isPulling = () => {
                const pulling = activePulling();
                return Boolean(
                  pulling &&
                  pulling.model === model.name &&
                  pulling.runtime === activeRuntime(),
                );
              };
              const isQueued = () => backend.isModelPullQueued(model.name, activeRuntime());
              const sizeLabel = () => {
                const size = variant()?.size_bytes;
                if (typeof size !== "number" || size <= 0) return "";
                const prefix = variant()?.size_estimated ? "~" : "";
                return ` ${prefix}${formatBytes(size)}`;
              };
              const statusText = () => {
                if (isPulling()) {
                  const progress = backend.downloadProgress();
                  if (
                    progress &&
                    progress.model === model.name &&
                    progress.runtime === activeRuntime()
                  ) {
                    const pct = Math.max(0, Math.min(100, Math.round(progress.percent)));
                    return `${spinnerFrame()} ${pct}%`;
                  }
                  return `${spinnerFrame()} pulling`;
                }
                if (isQueued()) return "queued";
                if (isActive()) return "● selected";
                return variant()?.installed ? "● pulled" : "";
              };
              const statusColor = () => {
                if (isPulling()) return colors().transcribing;
                if (isQueued()) return colors().accent;
                if (isActive()) return colors().secondary;
                return variant()?.installed ? colors().success : colors().textDim;
              };

              return (
                <box
                  flexDirection="row"
                  paddingRight={1}
                  backgroundColor={isSelected() ? colors().backgroundElement : undefined}
                  onMouseUp={() => props.onSelectModel(index())}
                >
                  <box
                    width={1}
                    backgroundColor={isSelected() ? colors().secondary : undefined}
                  />
                  <box flexDirection="row" width="100%" paddingLeft={1}>
                    <box flexGrow={1}>
                      <text>
                        <span style={{ fg: isSelected() ? colors().text : colors().textMuted }}>
                          {model.name}
                        </span>
                        <span style={{ fg: colors().textDim }}>{sizeLabel()}</span>
                      </text>
                    </box>
                    <box width={14}>
                      <text>
                        <span style={{ fg: statusColor() }}>{statusText()}</span>
                      </text>
                    </box>
                  </box>
                </box>
              );
            }}
          </For>
        </box>
      </scrollbox>

      <Show when={selectedModel()}>
        <box paddingTop={0} flexShrink={0}>
          <text>
            <span style={{ fg: colors().textDim }}>
              {MODEL_DESCRIPTIONS[selectedModel()!.name] ?? ""}
            </span>
          </text>
        </box>
      </Show>

      <box flexDirection="row" gap={2} paddingTop={1} flexShrink={0}>
        <CommandHint
          keys="Enter"
          label={
            selectedModelIsPulling()
              ? "cancel"
              : selectedModelIsQueued()
                ? "cancel queued"
              : (selectedModel()?.variants?.[activeRuntime()]?.installed ? "select" : "pull + select")
          }
          onClick={handlePullOrSelect}
        />
      </box>
    </box>
  );
}

// ---------------------------------------------------------------------------
// Step 5: Ready
// ---------------------------------------------------------------------------

function ReadyStep(props: { firstRun: boolean }): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();

  const modelName = () => backend.config()?.model.name ?? "-";
  const runtimeName = () => backend.config()?.model.runtime ?? "-";
  const device = () => formatDeviceLabel(backend.config()?.model.device);

  return (
    <box flexDirection="column" gap={1} paddingX={2} paddingY={1} flexShrink={0}>
      <Show when={props.firstRun} fallback={
        <SectionTitle text="Quick reference" />
      }>
        <text>
          <span style={{ fg: colors().success, bold: true }}>You're all set!</span>
        </text>
      </Show>

      <Show when={props.firstRun}>
        <box flexDirection="column" gap={0}>
          <text>
            <span style={{ fg: colors().textMuted }}>Runtime: </span>
            <span style={{ fg: colors().text }}>{runtimeName()}</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>Device: </span>
            <span style={{ fg: colors().text }}>{device()}</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>Model: </span>
            <span style={{ fg: colors().text }}>{modelName()}</span>
          </text>
        </box>
      </Show>

      <box flexDirection="column" gap={0} marginTop={1}>
        <text>
          <span style={{ fg: colors().primary, bold: true }}>Getting started:</span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>Press the global hotkey (default </span>
          <span style={{ fg: colors().accent, bold: true }}>F3</span>
          <span style={{ fg: colors().textMuted }}>) to start recording from any app.</span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>Or click the status indicator in the footer.</span>
        </text>
      </box>

      <box flexDirection="column" gap={0} marginTop={1}>
        <text>
          <span style={{ fg: colors().textDim }}>Press </span>
          <span style={{ fg: colors().accent, bold: true }}>?</span>
          <span style={{ fg: colors().textDim }}> anytime to re-open this guide.</span>
        </text>
      </box>
    </box>
  );
}

// ---------------------------------------------------------------------------
// Main Welcome component
// ---------------------------------------------------------------------------

export function Welcome(): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const dialog = useDialog();
  const terminal = useTerminalDimensions();

  const dialogData = createMemo<WelcomeDialogData>(
    () => (dialog.currentDialog()?.data as WelcomeDialogData | undefined) ?? {},
  );
  const firstRun = createMemo(() => Boolean(dialogData().firstRun));
  const setupRequired = createMemo(() => Boolean(backend.config()?.first_run_setup_required));

  // Step management
  const steps = createMemo(() => {
    if (firstRun()) {
      return ["welcome", "ui-guide", "device-detection", "model-download", "ready"] as const;
    }
    return ["welcome", "ui-guide", "ready"] as const;
  });

  const initialStepIndex = () => {
    const raw = Number(dialogData().resumeStepIndex ?? 0);
    if (!Number.isFinite(raw)) return 0;
    const normalized = Math.floor(raw);
    return Math.max(0, Math.min(steps().length - 1, normalized));
  };
  const [stepIndex, setStepIndex] = createSignal(initialStepIndex());
  const currentStep = () => steps()[stepIndex()] ?? "welcome";
  const isLastStep = () => stepIndex() >= steps().length - 1;
  const isFirstStep = () => stepIndex() === 0;

  const initialModelIndex = () => {
    const raw = Number(dialogData().resumeModelIndex ?? 2);
    if (!Number.isFinite(raw)) return 2;
    return Math.max(0, Math.floor(raw));
  };
  const [modelIndex, setModelIndex] = createSignal(initialModelIndex()); // Default to "small"
  const hardwareFields: HardwareSettingField[] = ["runtime", "device"];
  const [selectedHardwareFieldIndex, setSelectedHardwareFieldIndex] = createSignal(0);
  const selectedHardwareField = createMemo<HardwareSettingField>(
    () => hardwareFields[selectedHardwareFieldIndex()] ?? "runtime",
  );
  const [recommendationAutoApplied, setRecommendationAutoApplied] = createSignal(
    Boolean(dialogData().recommendationAutoApplied),
  );
  const [recommendationAutoApplyInFlight, setRecommendationAutoApplyInFlight] = createSignal(
    false,
  );

  const recommendedRuntime = createMemo<RuntimeName | null>(() => {
    const value = backend.capabilitiesResponse()?.recommended.runtime;
    if (value === "faster-whisper" || value === "whisper.cpp") {
      return value;
    }
    return null;
  });

  const recommendedDevice = createMemo<"cpu" | "cuda" | "mps" | null>(() => {
    const value = backend.capabilitiesResponse()?.recommended.device;
    if (value === "cpu" || value === "cuda" || value === "mps") {
      return value;
    }
    return null;
  });

  function buildWelcomeResumeData(): WelcomeDialogData {
    return {
      firstRun: firstRun(),
      resumeStepIndex: stepIndex(),
      resumeModelIndex: modelIndex(),
      recommendationAutoApplied: recommendationAutoApplied(),
    };
  }

  function openHardwareSettingSelector(field: HardwareSettingField) {
    const settingId: SelectSettingId = field === "runtime" ? "model.runtime" : "model.device";
    dialog.openDialog("settings-select", {
      settingId,
      returnToDialog: "welcome",
      returnWelcomeData: buildWelcomeResumeData(),
    });
  }

  // Request capabilities when entering device detection step
  createEffect(on(() => currentStep(), (step) => {
    if (step === "device-detection") {
      backend.requestCapabilities();
    }
  }));

  // Auto-apply hardware recommendation once per welcome session on first run:
  // apply runtime first, then apply device after runtime config is reflected.
  createEffect(() => {
    if (!firstRun() || currentStep() !== "device-detection") return;
    if (recommendationAutoApplied() || recommendationAutoApplyInFlight()) return;
    const targetRuntime = recommendedRuntime();
    const targetDevice = recommendedDevice();
    if (!targetRuntime || !targetDevice) return;
    setRecommendationAutoApplyInFlight(true);
    backend.send({ type: "set_model_runtime", runtime: targetRuntime });
  });

  createEffect(() => {
    if (!recommendationAutoApplyInFlight() || recommendationAutoApplied()) return;
    const targetRuntime = recommendedRuntime();
    const targetDevice = recommendedDevice();
    const cfg = backend.config();
    if (!targetRuntime || !targetDevice || !cfg) return;
    if (cfg.model.runtime !== targetRuntime) return;
    backend.send({ type: "set_model_device", device: targetDevice });
    setRecommendationAutoApplied(true);
    setRecommendationAutoApplyInFlight(false);
  });

  // Clamp model index when models list changes
  createEffect(on(() => backend.models(), (models) => {
    if (models.length > 0 && modelIndex() >= models.length) {
      setModelIndex(models.length - 1);
    }
  }));

  const modalWidth = () => Math.min(76, Math.max(50, terminal().width - 8));
  const modalHeight = createMemo(() => {
    const minH = 18;
    const maxH = Math.max(minH, terminal().height - 4);
    const preferred = Math.floor(terminal().height * 0.75);
    return Math.max(minH, Math.min(preferred, maxH));
  });

  function canClose() {
    if (firstRun() && setupRequired()) return false;
    return true;
  }

  function handleClose() {
    if (!canClose()) return;
    if (firstRun()) {
      backend.send({ type: "set_welcome_shown" });
    }
    dialog.closeDialog();
  }

  const unregisterDismissHandler = dialog.registerDismissHandler("welcome", handleClose);
  onCleanup(unregisterDismissHandler);

  function handleNext() {
    if (isLastStep()) {
      handleClose();
      return;
    }
    setStepIndex((i) => Math.min(steps().length - 1, i + 1));
  }

  function handleBack() {
    setStepIndex((i) => Math.max(0, i - 1));
  }

  // Keyboard navigation
  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "welcome") return;

    if (currentStep() === "device-detection") {
      if (key.name === "up" || key.name === "k") {
        key.preventDefault();
        setSelectedHardwareFieldIndex((value) => Math.max(0, value - 1));
        return;
      }
      if (key.name === "down" || key.name === "j") {
        key.preventDefault();
        setSelectedHardwareFieldIndex((value) => Math.min(hardwareFields.length - 1, value + 1));
        return;
      }
      if (key.name === "return" || key.name === "enter") {
        key.preventDefault();
        openHardwareSettingSelector(selectedHardwareField());
        return;
      }
    }

    // Model download step: arrow keys navigate model list
    if (currentStep() === "model-download") {
      if (key.name === "up" || key.name === "k") {
        key.preventDefault();
        setModelIndex((i) => Math.max(0, i - 1));
        return;
      }
      if (key.name === "down" || key.name === "j") {
        key.preventDefault();
        setModelIndex((i) => Math.min(backend.models().length - 1, i + 1));
        return;
      }
      if (key.name === "return" || key.name === "enter") {
        key.preventDefault();
        const model = backend.models()[modelIndex()];
        const op = backend.activeModelOp();
        const activeRuntime = (backend.config()?.model.runtime as RuntimeName | undefined) ?? "faster-whisper";
        if (!model) return;
        const pullingOp =
          op?.type === "pulling" &&
          op.model === model.name &&
          op.runtime === activeRuntime
            ? op
            : null;
        const queued = backend.isModelPullQueued(model.name, activeRuntime);
        if (pullingOp) {
          backend.cancelModelDownload(model.name, pullingOp.runtime);
        } else if (queued) {
          backend.cancelModelDownload(model.name, activeRuntime);
        } else if (model.variants?.[activeRuntime]?.installed) {
          if (op) return;
          backend.send({ type: "set_selected_model", name: model.name });
        } else {
          backend.downloadModel(model.name, activeRuntime);
        }
        return;
      }
      if (key.name === "x") {
        const pulling = backend.activeModelOp();
        if (pulling?.type === "pulling") {
          backend.cancelModelDownload(pulling.model, pulling.runtime);
        }
        return;
      }
    }

    switch (key.name) {
      case "escape":
      case "q":
        if (canClose()) {
          handleClose();
        }
        break;
      case "return":
      case "enter":
        // Enter is handled in step-specific flows above where needed.
        if (currentStep() !== "model-download" && currentStep() !== "device-detection") {
          handleNext();
        }
        break;
      case "right":
        handleNext();
        break;
      case "left":
        handleBack();
        break;
    }
  });

  // Step indicator dots
  const stepDots = () => {
    return steps().map((_, i) => i === stepIndex() ? "●" : "○").join(" ");
  };

  return (
    <box
      flexDirection="column"
      width={modalWidth()}
      height={modalHeight()}
      backgroundColor={colors().backgroundPanel}
      padding={1}
    >
      {/* Header */}
      <box paddingX={2} paddingTop={1} paddingBottom={0} flexDirection="column" flexShrink={0}>
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>
              {firstRun() ? "Getting Started" : "Help"}
            </span>
          </text>
          <box flexDirection="row" alignItems="center" gap={2}>
            <text>
              <span style={{ fg: colors().textMuted }}>
                step {stepIndex() + 1} of {steps().length}
              </span>
            </text>
            <Show when={canClose()}>
              <box backgroundColor={colors().error} paddingX={1} onMouseUp={handleClose}>
                <text>
                  <span style={{ fg: colors().selectedText }}>esc</span>
                </text>
              </box>
            </Show>
          </box>
        </box>
        <box flexDirection="row" width="100%" marginTop={0}>
          <box width={3} borderStyle="single" border={["bottom"]} borderColor={colors().secondary} />
          <box flexGrow={1} borderStyle="single" border={["bottom"]} borderColor={colors().borderSubtle} />
        </box>
      </box>

      {/* Content – scrollable middle section, static header/footer stay fixed */}
      <Show when={currentStep() === "welcome"}>
        <scrollbox flexGrow={1} flexShrink={1}>
          <WelcomeStep />
        </scrollbox>
      </Show>
      <Show when={currentStep() === "ui-guide"}>
        <scrollbox flexGrow={1} flexShrink={1}>
          <UIGuideStep />
        </scrollbox>
      </Show>
      <Show when={currentStep() === "device-detection"}>
        <scrollbox flexGrow={1} flexShrink={1}>
          <DeviceDetectionStep
            caps={backend.capabilitiesResponse()}
            selectedField={selectedHardwareField()}
            onSelectField={(field) => {
              const idx = hardwareFields.indexOf(field);
              if (idx >= 0) {
                setSelectedHardwareFieldIndex(idx);
              }
            }}
            onOpenSelector={openHardwareSettingSelector}
          />
        </scrollbox>
      </Show>
      <Show when={currentStep() === "model-download"}>
        <box flexGrow={1} flexShrink={1} flexDirection="column">
          <ModelDownloadStep
            selectedModelIndex={modelIndex()}
            onSelectModel={setModelIndex}
          />
        </box>
      </Show>
      <Show when={currentStep() === "ready"}>
        <scrollbox flexGrow={1} flexShrink={1}>
          <ReadyStep firstRun={firstRun()} />
        </scrollbox>
      </Show>

      {/* Footer navigation */}
      <box paddingX={2} paddingTop={1} flexShrink={0}>
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <box flexDirection="row" gap={2}>
            <Show when={!isFirstStep()}>
              <CommandHint keys="Left" label="back" onClick={handleBack} />
            </Show>
            <CommandHint
              keys={isLastStep() ? "Enter" : "Right"}
              label={isLastStep() ? (firstRun() ? "finish" : "close") : "next"}
              onClick={handleNext}
            />
          </box>
          <text>
            <span style={{ fg: colors().textDim }}>{stepDots()}</span>
          </text>
        </box>
      </box>
    </box>
  );
}
