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

export function ModelManager(): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const dialog = useDialog();

  const [selectedIndex, setSelectedIndex] = createSignal(0);
  const [status, setStatus] = createSignal("");

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
    if (!model) return;
    setStatus(`Downloading ${model.name}...`);
    backend.send({ type: "download_model", name: model.name });
  }

  function handleRemove() {
    const model = selectedModel();
    if (!model || !model.installed) return;
    setStatus(`Removing ${model.name}...`);
    backend.send({ type: "remove_model", name: model.name });
  }

  function handleSetDefault() {
    const model = selectedModel();
    if (!model || !model.installed) return;
    backend.send({ type: "set_default_model", name: model.name });
    setStatus(`Default set to ${model.name}`);
  }

  function handleRefresh() {
    backend.send({ type: "list_models" });
    setStatus("Refreshed");
  }

  return (
    <box
      flexDirection="column"
      width={60}
      height={20}
      backgroundColor={colors().backgroundPanel}
      borderStyle="rounded"
      borderColor={colors().border}
      padding={1}
    >
      {/* Header */}
      <box paddingX={1} paddingBottom={1}>
        <text>
          <span fg={colors().primary}>◆</span>
          <span fg={colors().text}> Models</span>
        </text>
      </box>

      {/* Divider */}
      <box paddingX={1}>
        <text>
          <span fg={colors().borderSubtle}>
            {"─".repeat(56)}
          </span>
        </text>
      </box>

      {/* Model list */}
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

      {/* Status */}
      <Show when={status()}>
        <box paddingX={1} paddingTop={1}>
          <text>
            <span fg={colors().textMuted}>{status()}</span>
          </text>
        </box>
      </Show>

      {/* Footer */}
      <box paddingX={1} paddingTop={1}>
        <text>
          <span fg={colors().textDim}>[p]</span>
          <span fg={colors().textMuted}> pull </span>
          <span fg={colors().textDim}>[r]</span>
          <span fg={colors().textMuted}> remove </span>
          <span fg={colors().textDim}>[d]</span>
          <span fg={colors().textMuted}> default </span>
          <span fg={colors().textDim}>[l]</span>
          <span fg={colors().textMuted}> refresh </span>
          <span fg={colors().textDim}>[esc]</span>
          <span fg={colors().textMuted}> close</span>
        </text>
      </box>
    </box>
  );
}
