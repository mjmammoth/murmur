import { createMemo, onCleanup, type JSX } from "solid-js";
import { useKeyHandler, useRenderer } from "@opentui/solid";
import { type KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useDialog } from "../context/dialog";
import { useBackend } from "../context/backend";
import { exitApp } from "../util/exit";
import type { ExitConfirmDialogData } from "../types";

/**
 * Render a modal prompting the user to confirm exiting while a model download is in progress.
 *
 * The modal shows the current model name and download progress (when available) and
 * binds keyboard shortcuts to either cancel (Esc / N) or confirm exit (Enter / Y / Q / Ctrl+C).
 *
 * @returns A JSX element representing the exit confirmation modal
 */
export function ExitConfirmModal(): JSX.Element {
  const { colors } = useTheme();
  const dialog = useDialog();
  const backend = useBackend();
  const renderer = useRenderer();

  const dialogData = createMemo<ExitConfirmDialogData>(
    () => (dialog.currentDialog()?.data as ExitConfirmDialogData | undefined) ?? {},
  );

  const modelName = createMemo(() => {
    const explicitModel = dialogData().model?.trim();
    if (explicitModel) return explicitModel;
    const op = backend.activeModelOp();
    if (op?.type === "pulling") return op.model;
    return "selected model";
  });

  const runtimeName = createMemo(() => {
    const explicitRuntime = dialogData().runtime?.trim();
    if (explicitRuntime) return explicitRuntime;
    const op = backend.activeModelOp();
    if (op?.type === "pulling") return op.runtime;
    return backend.config()?.model.runtime ?? "faster-whisper";
  });

  const progressText = createMemo(() => {
    const progress = backend.downloadProgress();
    if (!progress || progress.model !== modelName() || progress.runtime !== runtimeName()) return "";
    const percent = Math.max(0, Math.min(99, Math.floor(progress.percent || 0)));
    return `${percent}% downloaded`;
  });

  /**
   * Closes the currently open dialog in the dialog context.
   */
  function cancelExit() {
    dialog.closeDialog();
  }

  const unregisterDismissHandler = dialog.registerDismissHandler("exit-confirm", cancelExit);
  onCleanup(unregisterDismissHandler);

  /**
   * Cancel all pending model downloads and exit the application.
   */
  function confirmExit() {
    backend.cancelAllModelDownloads();
    exitApp(renderer);
  }

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "exit-confirm") return;
    if (key.eventType === "release" || key.repeated) return;

    key.preventDefault();

    if (key.name === "escape" || key.name === "n") {
      cancelExit();
      return;
    }

    if (
      key.name === "return" ||
      key.name === "enter" ||
      key.name === "y" ||
      key.name === "q" ||
      (key.ctrl && key.name === "c")
    ) {
      confirmExit();
    }
  });

  return (
    <box
      flexDirection="column"
      width={62}
      backgroundColor={colors().backgroundPanel}
      borderStyle="single"
      borderColor={colors().borderSubtle}
      paddingY={1}
    >
      <box paddingX={3} paddingTop={1} flexDirection="column" gap={1}>
        <text>
          <span style={{ fg: colors().warning, bold: true }}>Download in progress</span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>Model: </span>
          <span style={{ fg: colors().text }}>{modelName()}</span>
          <span style={{ fg: colors().textMuted }}>{` (${runtimeName()})`}</span>
          <span style={{ fg: colors().textDim }}>{progressText() ? ` (${progressText()})` : ""}</span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>
            Exit now to cancel the download and clean up incomplete files?
          </span>
        </text>
      </box>

      <box paddingX={3} paddingTop={1} flexDirection="row" alignItems="center" gap={2} onMouseUp={confirmExit}>
        <box backgroundColor={colors().error} paddingX={1}>
          <text>
            <span style={{ fg: colors().selectedText }}>enter/y</span>
          </text>
        </box>
        <text>
          <span style={{ fg: colors().textMuted }}>exit and cancel download</span>
        </text>
      </box>

      <box paddingX={3} paddingTop={1} flexDirection="row" alignItems="center" gap={2} onMouseUp={cancelExit}>
        <box backgroundColor={colors().accent} paddingX={1}>
          <text>
            <span style={{ fg: colors().selectedText }}>esc/n</span>
          </text>
        </box>
        <text>
          <span style={{ fg: colors().textMuted }}>continue downloading</span>
        </text>
      </box>
    </box>
  );
}
