import {
  createSignal,
  createEffect,
  createMemo,
  onMount,
  For,
  Show,
  type JSX,
} from "solid-js";
import { useKeyHandler, useTerminalDimensions } from "@opentui/solid";
import type { KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import { useDialog } from "../context/dialog";
import { useConfig } from "../context/config";
import { ModelItem } from "./model-item";
import { useSpinnerFrame } from "./spinner";

interface ModelManagerDialogData {
  returnToSettings?: boolean;
  firstRunSetup?: boolean;
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function buildProgressBar(percent: number, width = 24): string {
  const safePercent = clampPercent(percent);
  const filled = Math.round((safePercent / 100) * width);
  const empty = Math.max(0, width - filled);
  return `[${"#".repeat(filled)}${"-".repeat(empty)}] ${safePercent}%`;
}

function CommandHint(props: { keys: string; label: string }): JSX.Element {
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

export function ModelManager(): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const config = useConfig();
  const dialog = useDialog();
  const terminal = useTerminalDimensions();

  const [selectedIndex, setSelectedIndex] = createSignal(0);
  const [statusMessage, setStatusMessage] = createSignal("");
  const spinnerFrame = useSpinnerFrame();
  const dialogData = createMemo<ModelManagerDialogData>(
    () => (dialog.currentDialog()?.data as ModelManagerDialogData | undefined) ?? {},
  );
  const returnToSettings = createMemo(() => Boolean(dialogData().returnToSettings));
  const firstRunSetup = createMemo(() => Boolean(dialogData().firstRunSetup));
  const setupRequired = createMemo(() => Boolean(backend.config()?.first_run_setup_required));
  const setupLocked = createMemo(() => firstRunSetup() && setupRequired());

  function closeManager() {
    if (setupLocked()) {
      setStatusMessage("First run setup: download and select a model to continue.");
      return;
    }
    if (returnToSettings()) {
      dialog.openDialog("settings");
      return;
    }
    dialog.closeDialog();
  }

  onMount(() => {
    backend.send({ type: "list_models" });
  });

  createEffect(() => {
    const models = backend.models();
    if (models.length > 0 && selectedIndex() >= models.length) {
      setSelectedIndex(models.length - 1);
    }
  });

  const selectedModel = () => {
    const models = backend.models();
    const idx = selectedIndex();
    if (idx < 0 || idx >= models.length) return null;
    return models[idx];
  };

  const primaryActionLabel = createMemo(() => {
    const model = selectedModel();
    if (!model) return "pull/select";
    return model.installed ? "select" : "pull";
  });

  const modalHeight = createMemo(() => {
    const minHeight = 16;
    const maxHeight = Math.max(minHeight, terminal().height - 4);
    const preferred = Math.floor(terminal().height * 0.68);
    return Math.max(minHeight, Math.min(preferred, maxHeight));
  });

  const selectedModelName = createMemo(() => config.config()?.model.name ?? null);

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "model-manager") return;

    const models = backend.models();
    const keyName = key.name;

    switch (keyName) {
      case "escape":
        closeManager();
        break;
      case "up":
      case "k":
        setSelectedIndex((idx) => Math.max(0, idx - 1));
        break;
      case "down":
      case "j":
        setSelectedIndex((idx) => Math.min(models.length - 1, idx + 1));
        break;
      case "return":
      case "enter":
        handlePrimaryAction();
        break;
      case "r":
      case "backspace":
        handleRemove();
        break;
    }
  });

  function handlePrimaryAction() {
    const model = selectedModel();
    if (!model || backend.activeModelOp()) return;
    if (model.installed) {
      handleSelect();
      return;
    }
    handlePull();
  }

  function handlePull() {
    const model = selectedModel();
    if (!model || backend.activeModelOp()) return;
    setStatusMessage("");
    backend.downloadModel(model.name);
  }

  function handleRemove() {
    const model = selectedModel();
    if (!model || !model.installed || backend.activeModelOp()) return;
    setStatusMessage("");
    backend.removeModel(model.name);
  }

  function handleSelect() {
    const model = selectedModel();
    if (!model || !model.installed) return;
    backend.send({ type: "set_selected_model", name: model.name });
    setStatusMessage(`Selected ${model.name}`);
  }

  const activePullProgress = createMemo(() => {
    const op = backend.activeModelOp();
    if (!op || op.type !== "pulling") return null;
    const progress = backend.downloadProgress();
    if (!progress || progress.model !== op.model) return null;
    return clampPercent(progress.percent);
  });

  const statusDisplay = () => {
    const op = backend.activeModelOp();
    if (op) {
      const progressPercent = activePullProgress();
      if (op.type === "pulling" && progressPercent !== null) {
        if (progressPercent >= 100) {
          return `${spinnerFrame()} Finalizing ${op.model}...`;
        }
        return `${spinnerFrame()} Downloading ${op.model}... ${progressPercent}%`;
      }
      const label = op.type === "pulling" ? "Downloading" : "Removing";
      return `${spinnerFrame()} ${label} ${op.model}...`;
    }
    return statusMessage();
  };

  const progressDisplay = createMemo(() => {
    const progressPercent = activePullProgress();
    if (progressPercent === null) return "";
    return buildProgressBar(progressPercent);
  });

  const statusColor = () => {
    const op = backend.activeModelOp();
    if (op) {
      return op.type === "pulling" ? colors().transcribing : colors().warning;
    }
    return colors().textMuted;
  };

  return (
    <box
      flexDirection="column"
      width={72}
      height={modalHeight()}
      backgroundColor={colors().backgroundPanel}
      padding={1}
    >
      <box paddingX={2} paddingTop={1} paddingBottom={0} flexDirection="column" flexShrink={0}>
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>Models</span>
          </text>
          <box flexDirection="row" alignItems="center" gap={2}>
            <text>
              <span style={{ fg: colors().textMuted }}>
                {setupLocked() ? "first run setup required" : "pull and selection"}
              </span>
            </text>
            <Show
              when={!setupLocked()}
              fallback={(
                <text>
                  <span style={{ fg: colors().warning }}>locked</span>
                </text>
              )}
            >
              <box backgroundColor={colors().secondary} paddingX={1}>
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

      <Show when={firstRunSetup()}>
        <box paddingX={2} paddingTop={1} flexDirection="column" flexShrink={0}>
          <text>
            <span style={{ fg: colors().warning, bold: true }}>First run setup (one-time)</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>Download and select a model to continue.</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>This appears only when no models are installed.</span>
          </text>
        </box>
      </Show>

      <scrollbox flexGrow={1} flexShrink={1} paddingY={1}>
        <box flexDirection="column">
          <For each={backend.models()}>
            {(model, index) => (
              <ModelItem
                model={model}
                selected={index() === selectedIndex()}
                isSelectedModel={model.name === selectedModelName()}
              />
            )}
          </For>
        </box>
      </scrollbox>

      <Show when={statusDisplay()}>
        <box paddingX={2} paddingTop={1} flexShrink={0}>
          <text>
            <span style={{ fg: statusColor() }}>{statusDisplay()}</span>
          </text>
        </box>
      </Show>

      <Show when={progressDisplay()}>
        <box paddingX={2} flexShrink={0}>
          <text>
            <span style={{ fg: colors().textMuted }}>{progressDisplay()}</span>
          </text>
        </box>
      </Show>

      <box paddingX={2} paddingTop={1} flexShrink={0}>
        <box flexDirection="row" gap={2} alignItems="center">
          <CommandHint keys="enter" label={primaryActionLabel()} />
          <CommandHint keys="r/backspace" label="remove" />
        </box>
      </box>
    </box>
  );
}
