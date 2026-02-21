import { createMemo, onCleanup, type JSX } from "solid-js";
import { useKeyHandler } from "@opentui/solid";
import { type KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useDialog } from "../context/dialog";
import type { RuntimeSwitchConfirmDialogData } from "../types";

export function isRuntimeSwitchConfirmDialogData(
  data: unknown,
): data is RuntimeSwitchConfirmDialogData {
  if (!data || typeof data !== "object") return false;
  const candidate = data as {
    runtime?: unknown;
    model?: unknown;
    format?: unknown;
  };
  const runtime = candidate.runtime;
  const runtimeValid = runtime === "faster-whisper" || runtime === "whisper.cpp";
  return (
    runtimeValid &&
    typeof candidate.model === "string" &&
    candidate.model.trim().length > 0 &&
    typeof candidate.format === "string" &&
    candidate.format.trim().length > 0
  );
}

export function RuntimeSwitchConfirmModal(): JSX.Element {
  const { colors } = useTheme();
  const dialog = useDialog();

  const dialogData = createMemo<RuntimeSwitchConfirmDialogData | null>(() => {
    const current = dialog.currentDialog();
    if (current?.type !== "runtime-switch-confirm") return null;
    return isRuntimeSwitchConfirmDialogData(current.data) ? current.data : null;
  });

  function cancel() {
    dialog.closeDialog();
  }

  function confirm() {
    const data = dialogData();
    if (!data) {
      cancel();
      return;
    }
    dialog.openDialog("model-manager", {
      pendingRuntimeSwitch: {
        runtime: data.runtime,
        model: data.model,
        format: data.format,
      },
    });
  }

  const unregisterDismissHandler = dialog.registerDismissHandler("runtime-switch-confirm", cancel);
  onCleanup(unregisterDismissHandler);

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "runtime-switch-confirm") return;
    if (!dialogData()) return;
    if (key.eventType === "release" || key.repeated) return;

    key.preventDefault();
    if (key.name === "escape" || key.name === "n") {
      cancel();
      return;
    }
    if (key.name === "return" || key.name === "enter" || key.name === "y") {
      confirm();
    }
  });

  if (!dialogData()) return <></>;

  return (
    <box
      flexDirection="column"
      width={74}
      backgroundColor={colors().backgroundPanel}
      borderStyle="single"
      borderColor={colors().borderSubtle}
      paddingY={1}
    >
      <box paddingX={3} paddingTop={1} flexDirection="column" gap={1}>
        <text>
          <span style={{ fg: colors().warning, bold: true }}>
            Runtime switch requires model files
          </span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>Switch target: </span>
          <span style={{ fg: colors().text }}>{dialogData()!.runtime}</span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>Model: </span>
          <span style={{ fg: colors().text }}>{dialogData()!.model}</span>
          <span style={{ fg: colors().textDim }}>{` (${dialogData()!.format})`}</span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>
            This runtime uses separate model files. Continue to Model Manager and confirm
            downloading this variant?
          </span>
        </text>
      </box>

      <box paddingX={3} paddingTop={1} flexDirection="row" alignItems="center" gap={2} onMouseUp={confirm}>
        <box backgroundColor={colors().accent} paddingX={1}>
          <text>
            <span style={{ fg: colors().selectedText }}>enter/y</span>
          </text>
        </box>
        <text>
          <span style={{ fg: colors().textMuted }}>open model manager</span>
        </text>
      </box>

      <box paddingX={3} paddingTop={1} flexDirection="row" alignItems="center" gap={2} onMouseUp={cancel}>
        <box backgroundColor={colors().error} paddingX={1}>
          <text>
            <span style={{ fg: colors().selectedText }}>esc/n</span>
          </text>
        </box>
        <text>
          <span style={{ fg: colors().textMuted }}>stay on current runtime</span>
        </text>
      </box>
    </box>
  );
}
