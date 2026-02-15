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
import type { ModelManagerDialogData } from "../types";

/**
 * Render a compact key badge with an adjacent descriptive label for keyboard command hints.
 *
 * @param props.keys - The key or key sequence text displayed inside the colored badge (for example: "Esc", "Enter", "x/Enter").
 * @param props.label - The descriptive label shown next to the badge (for example: "close", "select").
 * @returns A JSX element containing a colored key badge and a muted label, arranged horizontally.
 */
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

/**
 * Renders the Models management dialog that lets users browse, download (pull), select, and remove models.
 *
 * The UI shows available models, the currently selected model, active operations (download/remove), and status messages.
 * It also handles keyboard shortcuts for navigation and actions when the dialog is active.
 *
 * @returns The JSX element for the Models management dialog
 */
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
  const returnSettingId = createMemo(() => dialogData().returnSettingId ?? null);
  const returnFilterQuery = createMemo(() => dialogData().returnFilterQuery ?? null);
  const firstRunSetup = createMemo(() => Boolean(dialogData().firstRunSetup));
  const setupRequired = createMemo(() => Boolean(backend.config()?.first_run_setup_required));
  const setupLocked = createMemo(() => firstRunSetup() && setupRequired());

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

  const activePullingModelName = createMemo(() => {
    const op = backend.activeModelOp();
    if (!op || op.type !== "pulling") return null;
    return op.model;
  });

  const selectedModelIsPulling = createMemo(() => {
    const model = selectedModel();
    const pullingModelName = activePullingModelName();
    return Boolean(model && pullingModelName && model.name === pullingModelName);
  });

  const primaryActionLabel = createMemo(() => {
    const model = selectedModel();
    if (!model) return "pull/select";
    if (selectedModelIsPulling()) return "cancel pull";
    return model.installed ? "select" : "pull + select";
  });

  const primaryActionKeys = createMemo(() => {
    if (selectedModelIsPulling()) return "x/enter";
    return "enter";
  });

  const modalHeight = createMemo(() => {
    const minHeight = 16;
    const maxHeight = Math.max(minHeight, terminal().height - 4);
    const preferred = Math.floor(terminal().height * 0.68);
    return Math.max(minHeight, Math.min(preferred, maxHeight));
  });

  const selectedModelName = createMemo(() => {
    const configured = config.config()?.model.name ?? null;
    if (!configured) return null;
    const match = backend.models().find((model) => model.name === configured);
    return match?.installed ? configured : null;
  });

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "model-manager") return;

    const models = backend.models();
    const keyName = key.name;

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
      case "r":
      case "backspace":
        handleRemove();
        break;
    }
  });

  /**
   * Perform the primary action for the currently highlighted model.
   *
   * If no model is selected, no action is taken. If the selected model is currently being downloaded,
   * the download is cancelled. If a different model operation is active, no action is taken. If the
   * selected model is installed, it is set as the active/selected model; otherwise a download for the
   * model is started.
   */
  function handlePrimaryAction() {
    const model = selectedModel();
    if (!model) return;
    if (selectedModelIsPulling()) {
      handleCancelDownload();
      return;
    }
    if (backend.activeModelOp()) return;
    if (model.installed) {
      handleSelect();
      return;
    }
    handlePull();
  }

  /**
   * Cancels the currently active model download if one exists.
   *
   * If no model is being downloaded, this function has no effect.
   */
  function handleCancelDownload() {
    const pullingModelName = activePullingModelName();
    if (!pullingModelName) return;
    backend.cancelModelDownload(pullingModelName);
  }

  /**
   * Starts downloading the currently selected model if one exists and no model operation is active.
   *
   * Clears the visible status message and requests the backend to download the selected model.
   * If there is no selected model or another model operation is in progress, this function does nothing.
   */
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

  const statusDisplay = () => {
    const op = backend.activeModelOp();
    if (op) {
      if (op.type === "removing") {
        return `${spinnerFrame()} Removing ${op.model}...`;
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

      <box paddingX={2} paddingTop={1} flexShrink={0}>
        <box flexDirection="row" gap={2} alignItems="center">
          <CommandHint keys={primaryActionKeys()} label={primaryActionLabel()} />
          <CommandHint keys="p" label="pull" />
          <CommandHint keys="r/backspace" label="remove" />
        </box>
      </box>
    </box>
  );
}