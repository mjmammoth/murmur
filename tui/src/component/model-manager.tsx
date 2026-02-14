import {
  createSignal,
  createEffect,
  createMemo,
  onMount,
  For,
  Show,
  type JSX,
} from "solid-js";
import { useKeyHandler } from "@opentui/solid";
import type { KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import { useDialog } from "../context/dialog";
import { ModelItem } from "./model-item";
import { useSpinnerFrame } from "./spinner";

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
 * Render the Model Manager dialog for browsing, downloading, removing, and selecting models.
 *
 * Displays the list of available models, highlights the current selection, shows ongoing
 * operation status (download/remove) with progress, and provides keyboard-driven commands
 * for pull (`p`), remove (`r`), select (`d`), refresh (`l`), navigation (`up`/`down`/`k`/`j`),
 * and close (`esc`). When closed, the dialog either returns to the settings dialog if the
 * dialog data requests it or simply closes.
 *
 * @returns The JSX element for the model manager dialog UI.
 */
export function ModelManager(): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const dialog = useDialog();

  const [selectedIndex, setSelectedIndex] = createSignal(0);
  const [statusMessage, setStatusMessage] = createSignal("");
  const spinnerFrame = useSpinnerFrame();
  const returnToSettings = createMemo(
    () => Boolean((dialog.currentDialog()?.data as { returnToSettings?: boolean } | undefined)?.returnToSettings),
  );

  function closeManager() {
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
      case "p":
        handlePull();
        break;
      case "r":
        handleRemove();
        break;
      case "d":
        handleSelect();
        break;
      case "l":
        handleRefresh();
        break;
    }
  });

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

  function handleRefresh() {
    backend.send({ type: "list_models" });
    setStatusMessage("Refreshed");
  }

  const statusDisplay = () => {
    const op = backend.activeModelOp();
    if (op) {
      const progress = backend.downloadProgress();
      if (op.type === "pulling" && progress && progress.model === op.model) {
        return `${spinnerFrame()} Downloading ${op.model}... ${progress.percent}%`;
      }
      const label = op.type === "pulling" ? "Downloading" : "Removing";
      return `${spinnerFrame()} ${label} ${op.model}...`;
    }
    return statusMessage();
  };

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
      height={24}
      backgroundColor={colors().backgroundPanel}
      borderStyle="single"
      borderColor={colors().borderSubtle}
      padding={1}
    >
      <box paddingX={2} paddingTop={1} paddingBottom={0} flexDirection="column">
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>Models</span>
          </text>
          <box flexDirection="row" alignItems="center" gap={2}>
            <text>
              <span style={{ fg: colors().textMuted }}>install and selection</span>
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

      <scrollbox flexGrow={1} paddingY={1}>
        <box flexDirection="column">
          <For each={backend.models()}>
            {(model, index) => (
              <ModelItem
                model={model}
                selected={index() === selectedIndex()}
              />
            )}
          </For>
        </box>
      </scrollbox>

      <Show when={statusDisplay()}>
        <box paddingX={2} paddingTop={1}>
          <text>
            <span style={{ fg: statusColor() }}>{statusDisplay()}</span>
          </text>
        </box>
      </Show>

      <box paddingX={2} paddingTop={1}>
        <box flexDirection="row" gap={2} alignItems="center">
          <CommandHint keys="p" label="pull" />
          <CommandHint keys="r" label="remove" />
          <CommandHint keys="d" label="select" />
          <CommandHint keys="l" label="refresh" />
        </box>
      </box>
    </box>
  );
}