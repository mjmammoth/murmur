import {
  createSignal,
  createEffect,
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

export function ModelManager(): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const dialog = useDialog();

  const [selectedIndex, setSelectedIndex] = createSignal(0);
  const [statusMessage, setStatusMessage] = createSignal("");
  const spinnerFrame = useSpinnerFrame();

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
        dialog.closeDialog();
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
        handleSetDefault();
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

  function handleSetDefault() {
    const model = selectedModel();
    if (!model || !model.installed) return;
    backend.send({ type: "set_default_model", name: model.name });
    setStatusMessage(`Default set to ${model.name}`);
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
      <box paddingX={2} paddingY={1} flexDirection="row" justifyContent="space-between">
        <text>
          <span style={{ fg: colors().secondary }}>■</span>
          <span style={{ fg: colors().primary }}> Models</span>
          <span style={{ fg: colors().textMuted }}> / install and defaults</span>
        </text>
        <box backgroundColor={colors().secondary} paddingX={1}>
          <text>
            <span style={{ fg: colors().selectedText }}>esc</span>
          </text>
        </box>
      </box>

      <box paddingX={1}>
        <text>
          <span style={{ fg: colors().borderSubtle }}>
            {"-".repeat(68)}
          </span>
        </text>
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
          <text>
            <span style={{ fg: colors().secondary }}>■</span>
          </text>
          <CommandHint keys="p" label="pull" />
          <CommandHint keys="r" label="remove" />
          <CommandHint keys="d" label="default" />
          <CommandHint keys="l" label="refresh" />
        </box>
      </box>
    </box>
  );
}
