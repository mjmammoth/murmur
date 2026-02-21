import {
  createSignal,
  createEffect,
  createMemo,
  onCleanup,
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
import { ModelItem, MODEL_TABLE_LAYOUT } from "./model-item";
import { useSpinnerFrame } from "./spinner";
import type { RuntimeName, ModelManagerDialogData } from "../types";

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

export function ModelManager(): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const config = useConfig();
  const dialog = useDialog();
  const terminal = useTerminalDimensions();

  const [selectedIndex, setSelectedIndex] = createSignal(0);
  const [statusMessage, setStatusMessage] = createSignal("");
  const [mouseArmedIndex, setMouseArmedIndex] = createSignal<number | null>(null);
  const [pendingSwitchConfirmVisible, setPendingSwitchConfirmVisible] = createSignal(false);
  const spinnerFrame = useSpinnerFrame();

  const dialogData = createMemo<ModelManagerDialogData>(
    () => (dialog.currentDialog()?.data as ModelManagerDialogData | undefined) ?? {},
  );
  const returnToSettings = createMemo(() => Boolean(dialogData().returnToSettings));
  const returnSettingId = createMemo(() => dialogData().returnSettingId ?? null);
  const returnFilterQuery = createMemo(() => dialogData().returnFilterQuery ?? null);
  const firstRunSetup = createMemo(() => Boolean(dialogData().firstRunSetup));
  const pendingRuntimeSwitch = createMemo(() => dialogData().pendingRuntimeSwitch ?? null);
  const setupRequired = createMemo(() => Boolean(backend.config()?.first_run_setup_required));
  const setupLocked = createMemo(() => firstRunSetup() && setupRequired());

  const activeRuntime = createMemo<RuntimeName>(
    () => (config.config()?.model.runtime as RuntimeName | undefined) ?? "faster-whisper",
  );

  function closeManager() {
    if (setupLocked()) {
      setStatusMessage("First run setup: download and select a model to continue.");
      return;
    }
    if (returnToSettings()) {
      const selectedSettingId = returnSettingId();
      const filterQuery = returnFilterQuery();
      dialog.openDialog(
        "settings",
        selectedSettingId || filterQuery
          ? { selectedSettingId: selectedSettingId ?? undefined, filterQuery: filterQuery ?? undefined }
          : undefined,
      );
      return;
    }
    dialog.closeDialog();
  }

  onMount(() => {
    const unregisterDismissHandler = dialog.registerDismissHandler("model-manager", closeManager);
    onCleanup(unregisterDismissHandler);
    backend.send({ type: "list_models" });
  });

  createEffect(() => {
    const models = backend.models();
    if (models.length > 0 && selectedIndex() >= models.length) {
      setSelectedIndex(models.length - 1);
    }
  });

  createEffect(() => {
    const selected = selectedIndex();
    if (mouseArmedIndex() !== selected) {
      setMouseArmedIndex(null);
    }
  });

  createEffect(() => {
    const pending = pendingRuntimeSwitch();
    setPendingSwitchConfirmVisible(Boolean(pending));
    if (!pending) return;
    const idx = backend.models().findIndex((model) => model.name === pending.model);
    if (idx >= 0) {
      setSelectedIndex(idx);
    }
  });

  const selectedModel = () => {
    const models = backend.models();
    const idx = selectedIndex();
    if (idx < 0 || idx >= models.length) return null;
    return models[idx];
  };

  const selectedModelVariant = createMemo(() => {
    const model = selectedModel();
    if (!model) return null;
    return model.variants[activeRuntime()] ?? null;
  });

  const activePullingModel = createMemo(() => {
    const op = backend.activeModelOp();
    if (!op || op.type !== "pulling") return null;
    return op;
  });

  const selectedModelIsPulling = createMemo(() => {
    const model = selectedModel();
    const pulling = activePullingModel();
    return Boolean(
      model &&
      pulling &&
      model.name === pulling.model &&
      pulling.runtime === activeRuntime(),
    );
  });

  const selectedModelIsQueued = createMemo(() => {
    const model = selectedModel();
    if (!model) return false;
    return backend.isModelPullQueued(model.name, activeRuntime());
  });

  const selectedModelInstalledOnActiveRuntime = createMemo(
    () => Boolean(selectedModelVariant()?.installed),
  );

  const primaryActionLabel = createMemo(() => {
    if (pendingSwitchConfirmVisible()) return "confirm download";
    const model = selectedModel();
    if (!model) return "pull/select";
    if (selectedModelIsPulling()) return "cancel pull";
    if (selectedModelIsQueued()) return "cancel queued";
    return selectedModelInstalledOnActiveRuntime() ? "select" : "pull + select";
  });

  const primaryActionKeys = createMemo(() => {
    if (selectedModelIsPulling() || selectedModelIsQueued()) return "x/enter";
    if (pendingSwitchConfirmVisible()) return "enter/y";
    return "enter";
  });

  const modalHeight = createMemo(() => {
    const minHeight = 18;
    const maxHeight = Math.max(minHeight, terminal().height - 4);
    const preferred = Math.floor(terminal().height * 0.72);
    return Math.max(minHeight, Math.min(preferred, maxHeight));
  });

  const selectedModelName = createMemo(() => {
    const configured = config.config()?.model.name ?? null;
    if (!configured) return null;
    const match = backend.models().find((model) => model.name === configured);
    const variant = match?.variants?.[activeRuntime()];
    return variant?.installed ? configured : null;
  });

  function confirmPendingSwitchDownload() {
    const pending = pendingRuntimeSwitch();
    if (!pending) return;
    setPendingSwitchConfirmVisible(false);
    setStatusMessage("");
    backend.downloadModel(pending.model, pending.runtime, pending.runtime);
  }

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "model-manager") return;

    const models = backend.models();
    const keyName = key.name;

    if (pendingSwitchConfirmVisible()) {
      switch (keyName) {
        case "escape":
        case "q":
        case "n":
          closeManager();
          return;
        case "return":
        case "enter":
        case "y":
          confirmPendingSwitchDownload();
          return;
      }
    }

    switch (keyName) {
      case "escape":
      case "q":
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
      case "p":
        handlePull();
        break;
      case "x":
        handleCancelDownload();
        break;
      case "backspace":
        handleRemove();
        break;
    }
  });

  function handlePrimaryAction() {
    if (pendingSwitchConfirmVisible()) {
      confirmPendingSwitchDownload();
      return;
    }

    const model = selectedModel();
    if (!model) return;
    if (selectedModelIsPulling()) {
      handleCancelDownload();
      return;
    }
    if (selectedModelIsQueued()) {
      handleCancelDownload();
      return;
    }
    if (selectedModelInstalledOnActiveRuntime()) {
      if (backend.activeModelOp()) return;
      handleSelect();
      return;
    }
    handlePull();
  }

  function handleCancelDownload() {
    const model = selectedModel();
    if (model && backend.isModelPullQueued(model.name, activeRuntime())) {
      backend.cancelModelDownload(model.name, activeRuntime());
      return;
    }
    const pulling = activePullingModel();
    if (!pulling) return;
    backend.cancelModelDownload(pulling.model, pulling.runtime);
  }

  function handlePull() {
    const model = selectedModel();
    if (!model) return;
    const op = backend.activeModelOp();
    const active = activeRuntime();
    if (op?.type === "pulling" && op.model === model.name && op.runtime === active) return;
    setStatusMessage("");
    backend.downloadModel(model.name, active);
  }

  function handleRemove() {
    const model = selectedModel();
    if (!model || !selectedModelInstalledOnActiveRuntime() || backend.activeModelOp()) return;
    setStatusMessage("");
    backend.removeModel(model.name, activeRuntime());
  }

  function handleSelect() {
    const model = selectedModel();
    if (!model || !selectedModelInstalledOnActiveRuntime()) return;
    backend.send({ type: "set_selected_model", name: model.name });
    setStatusMessage(`Selected ${model.name}`);
  }

  function handleModelClick(index: number) {
    if (selectedIndex() === index && mouseArmedIndex() === index) {
      handlePrimaryAction();
      setMouseArmedIndex(null);
      return;
    }

    setSelectedIndex(index);
    setMouseArmedIndex(index);
  }

  const statusDisplay = () => {
    const op = backend.activeModelOp();
    if (op) {
      if (op.type === "removing") {
        return `${spinnerFrame()} Removing ${op.model} (${op.runtime})...`;
      }
      return "";
    }
    return statusMessage();
  };

  const statusColor = () => {
    const op = backend.activeModelOp();
    if (op) {
      return op.type === "removing" ? colors().warning : colors().textMuted;
    }
    return colors().textMuted;
  };

  return (
    <box
      flexDirection="column"
      width={84}
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
            <Show when={setupLocked()}>
              <text>
                <span style={{ fg: colors().textMuted }}>first run setup required</span>
              </text>
            </Show>
            <Show
              when={!setupLocked()}
              fallback={(
                <text>
                  <span style={{ fg: colors().warning }}>locked</span>
                </text>
              )}
            >
              <box backgroundColor={colors().error} paddingX={1} onMouseUp={closeManager}>
                <text>
                  <span style={{ fg: colors().selectedText }}>esc/q</span>
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

      <box paddingX={2} paddingTop={1} flexDirection="column" flexShrink={0}>
        <text>
          <span style={{ fg: colors().textMuted }}>
            Download OpenAI Whisper models locally and select which to use for transcription.
          </span>
        </text>
      </box>

      <Show when={firstRunSetup()}>
        <box paddingX={2} paddingTop={1} flexDirection="column" flexShrink={0}>
          <text>
            <span style={{ fg: colors().warning, bold: true }}>First run setup</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>Download and select a model to continue.</span>
          </text>
        </box>
      </Show>

      <Show when={pendingSwitchConfirmVisible() && pendingRuntimeSwitch()}>
        <box paddingX={2} paddingTop={1} flexDirection="column" flexShrink={0}>
          <text>
            <span style={{ fg: colors().warning, bold: true }}>Runtime switch confirmation</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>
              {`Download ${pendingRuntimeSwitch()!.model} for ${pendingRuntimeSwitch()!.runtime}?`}
            </span>
          </text>
          <text>
            <span style={{ fg: colors().textDim }}>Enter/Y to confirm, Esc/N to cancel.</span>
          </text>
        </box>
      </Show>

      <box paddingX={2} paddingTop={1} flexShrink={0}>
        <box
          flexDirection="row"
          width="100%"
          borderStyle="single"
          border={["bottom"]}
          borderColor={colors().borderSubtle}
          paddingBottom={0}
        >
          <box width={MODEL_TABLE_LAYOUT.rowPrefix} />
          <box width={MODEL_TABLE_LAYOUT.model} justifyContent="flex-start" alignItems="center">
            <text>
              <span style={{ fg: colors().accent, bold: true }}>Model</span>
            </text>
          </box>
          <box width={MODEL_TABLE_LAYOUT.size} justifyContent="flex-end" alignItems="center">
            <text>
              <span style={{ fg: colors().accent, bold: true }}>Size</span>
            </text>
          </box>
          <box width={MODEL_TABLE_LAYOUT.separator} />
          <box width={MODEL_TABLE_LAYOUT.runtime} justifyContent="center" alignItems="center">
            <text>
              <span style={{ fg: colors().accent, bold: true }}>Downloaded</span>
            </text>
          </box>
        </box>
      </box>

      <scrollbox flexGrow={1} flexShrink={1} paddingY={1}>
        <box flexDirection="column">
          <For each={backend.models()}>
            {(model, index) => (
              <ModelItem
                model={model}
                selected={index() === selectedIndex()}
                isSelectedModel={model.name === selectedModelName()}
                onClick={() => handleModelClick(index())}
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

      <box paddingX={2} paddingTop={1} flexShrink={0}>
        <box flexDirection="row" gap={2} alignItems="center">
          <CommandHint keys={primaryActionKeys()} label={primaryActionLabel()} onClick={handlePrimaryAction} />
          <Show when={!pendingSwitchConfirmVisible()}>
            <CommandHint keys="p" label="pull" onClick={handlePull} />
          </Show>
          <Show when={!pendingSwitchConfirmVisible()}>
            <CommandHint keys="backspace" label="remove" onClick={handleRemove} />
          </Show>
        </box>
      </box>
    </box>
  );
}
