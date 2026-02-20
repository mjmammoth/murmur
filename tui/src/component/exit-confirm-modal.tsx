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

  const progressText = createMemo(() => {
    const progress = backend.downloadProgress();
    if (!progress || progress.model !== modelName()) return "";
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
   * Cancel the in-progress model download (if any) and exit the application.
   *
   * If a concrete model name is available and not the placeholder "selected model", requests the backend to cancel that model's download, then calls the renderer exit utility to terminate the app.
   */
  function confirmExit() {
    const model = modelName();
    if (model && model !== "selected model") {
      backend.cancelModelDownload(model);
    }
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
          <span style={{ fg: colors().textDim }}>{progressText() ? ` (${progressText()})` : ""}</span>
        </text>
        <text>
          <span style={{ fg: colors().textMuted }}>
            Exit now to cancel the download and clean up incomplete files?
          </span>
        </text>
      </box>

      <box paddingX={3} paddingTop={1} flexDirection="row" alignItems="center" gap={2} onMouseUp={confirmExit}>
        <box backgroundColor={colors().secondary} paddingX={1}>
          <text>
            <span style={{ fg: colors().selectedText }}>enter/y</span>
          </text>
        </box>
        <text>
          <span style={{ fg: colors().textMuted }}>exit and cancel download</span>
        </text>
      </box>

      <box paddingX={3} paddingTop={1} flexDirection="row" alignItems="center" gap={2} onMouseUp={cancelExit}>
        <box backgroundColor={colors().secondary} paddingX={1}>
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
