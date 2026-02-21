import { createEffect, createSignal, onCleanup, onMount, Show, type JSX } from "solid-js";
import { useKeyHandler, usePaste, useRenderer, useTerminalDimensions } from "@opentui/solid";
import { BorderChars, RGBA, type KeyEvent, type MouseEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import { useTranscriber } from "../context/transcriber";
import { useDialog } from "../context/dialog";
import { useToast } from "../context/toast";
import { Header } from "../component/header";
import { Footer } from "../component/footer";
import { TranscriptList } from "../component/transcript-list";
import { ToastContainer } from "../component/toast";
import { ModelManager } from "../component/model-manager";
import { Settings } from "../component/settings";
import { LOG_LEVELS, LogPanel } from "../component/log-panel";
import { HotkeyModal } from "../component/hotkey-modal";
import { SettingsSelectModal } from "../component/settings-select-modal";
import { ThemePickerModal } from "../component/theme-picker-modal";
import { SettingsEditModal } from "../component/settings-edit-modal";
import { ExitConfirmModal } from "../component/exit-confirm-modal";
import { RuntimeSwitchConfirmModal } from "../component/runtime-switch-confirm-modal";
import { Welcome } from "../component/welcome";
import { exitApp } from "../util/exit";
import { setSigintHandler } from "../util/interrupt";
import type { ModelManagerDialogData } from "../types";

/**
 * Render the application's Home screen and manage its UI state, global input handlers, backend interactions, and modal overlays.
 *
 * Renders the header, transcript list, footer, optional logs panel, toast container, and any active modal dialogs while coordinating keyboard shortcuts, paste handling, and backend requests.
 *
 * @returns The root JSX element for the Home screen layout
 */
export function Home(): JSX.Element {
  const LOGS_PANEL_WIDTH_COLS = 48;
  const LOGS_PANEL_MIN_TERMINAL_WIDTH = 115;
  const { colors } = useTheme();
  const renderer = useRenderer();
  const terminal = useTerminalDimensions();
  const backend = useBackend();
  const transcriber = useTranscriber();
  const dialog = useDialog();
  const toast = useToast();
  const [showLogs, setShowLogs] = createSignal(false);
  const [activePane, setActivePane] = createSignal<"main" | "logs">("main");
  const [logLevelIndex, setLogLevelIndex] = createSignal(1);
  const canShowLogs = () => terminal().width >= LOGS_PANEL_MIN_TERMINAL_WIDTH;
  const logsVisible = () => showLogs() && canShowLogs();
  const shouldSuppressPasteInput = () => Date.now() < backend.suppressPasteInputUntil();
  const homePaneWidth = () => {
    const fullWidth = terminal().width;
    if (!logsVisible()) return fullWidth;
    return Math.max(0, fullWidth - LOGS_PANEL_WIDTH_COLS);
  };
  const logsTooNarrowMessage = () => "UI too narrow for logs.";
  const firstRunSetupRequired = () => Boolean(backend.config()?.first_run_setup_required);
  const welcomeShown = () => Boolean(backend.config()?.ui?.welcome_shown);

  createEffect(() => {
    if (!logsVisible() && activePane() === "logs") {
      setActivePane("main");
    }
  });

  let previousLogsVisible = false;
  createEffect(() => {
    const currentlyVisible = logsVisible();
    if (previousLogsVisible && !currentlyVisible && showLogs() && !canShowLogs()) {
      toast.showToast(logsTooNarrowMessage(), { dedupeKey: "logs-too-narrow" });
    }
    previousLogsVisible = currentlyVisible;
  });

  createEffect(() => {
    if (!backend.connected()) return;
    backend.send({ type: "list_models" });
  });

  // Auto-open welcome journey when welcome_shown is false (first launch)
  // or when first_run_setup_required (no models installed).
  createEffect(() => {
    if (welcomeShown() && !firstRunSetupRequired()) return;
    const cfg = backend.config();
    if (!cfg) return;
    const models = backend.models();
    if (models.length === 0) return;

    const currentDialog = dialog.currentDialog();
    if (currentDialog) return;

    dialog.openDialog("welcome", { firstRun: !welcomeShown() || firstRunSetupRequired() });
  });

  createEffect(() => {
    backend.send({ type: "set_hotkey_blocked", enabled: dialog.isOpen() });
  });

  /**
   * Prompt for confirmation when a model is actively being pulled, otherwise exit the application.
   *
   * If a model pull operation is in progress and the exit-confirm dialog is not already open, opens the exit-confirm dialog for that model; in all other cases, exits the app immediately.
   */
  function requestExit() {
    const activeOp = backend.activeModelOp();
    const currentDialog = dialog.currentDialog();
    if (backend.hasPendingModelDownloads() && currentDialog?.type !== "exit-confirm") {
      dialog.openDialog(
        "exit-confirm",
        activeOp?.type === "pulling"
          ? { model: activeOp.model, runtime: activeOp.runtime }
          : undefined,
      );
      return;
    }
    exitApp(renderer);
  }

  onMount(() => {
    backend.onRuntimeSwitchRequired((payload) => {
      dialog.openDialog("runtime-switch-confirm", payload);
    });
  });

  function toggleLogsPanel() {
    setShowLogs((prev) => {
      const next = !prev;
      if (next && !canShowLogs()) {
        toast.showToast(logsTooNarrowMessage(), { dedupeKey: "logs-too-narrow" });
      }
      setActivePane(next && canShowLogs() ? "logs" : "main");
      return next;
    });
  }

  function toggleRecordingFromStatusClick() {
    if (dialog.isOpen()) return;

    const status = transcriber.status();
    if (status === "recording") {
      backend.send({ type: "stop_recording" });
      return;
    }

    if (status === "ready") {
      backend.send({ type: "start_recording" });
      return;
    }

    if (status === "connecting") {
      toast.showToast("Still connecting to backend.", { dedupeKey: "status-connecting-click" });
      return;
    }

    if (status === "transcribing" || status === "downloading") {
      toast.showToast("Busy right now. Try again when ready.", {
        dedupeKey: "status-busy-click",
      });
      return;
    }

    if (status === "error") {
      toast.showToast("Cannot start recording while status is error.");
    }
  }

  setSigintHandler(() => {
    requestExit();
  });
  onCleanup(() => {
    setSigintHandler(null);
  });

  useKeyHandler((key: KeyEvent) => {
    if (key.ctrl && key.name === "c") {
      key.preventDefault();
      requestExit();
      return;
    }

    if (shouldSuppressPasteInput()) {
      key.preventDefault();
      return;
    }

    // Log panel toggle works even with dialogs open
    if (key.name === "l" && !dialog.isOpen()) {
      toggleLogsPanel();
      return;
    }

    if (key.name === "escape" && logsVisible() && !dialog.isOpen()) {
      setShowLogs(false);
      setActivePane("main");
      return;
    }

    if (key.name === "tab" && logsVisible() && !dialog.isOpen()) {
      key.preventDefault();
      setActivePane((pane) => (pane === "main" ? "logs" : "main"));
      return;
    }

    if (
      logsVisible() &&
      activePane() === "logs" &&
      !dialog.isOpen() &&
      (key.name === "left" || key.name === "right")
    ) {
      key.preventDefault();
      if (key.name === "left") {
        setLogLevelIndex((idx) => Math.max(0, idx - 1));
      } else {
        setLogLevelIndex((idx) => Math.min(LOG_LEVELS.length - 1, idx + 1));
      }
      return;
    }

    if (dialog.isOpen()) return;

    if (logsVisible() && activePane() === "logs") {
      if (key.name === "up" || key.name === "down" || key.name === "j" || key.name === "k") {
        return;
      }
    }

    const keyName = key.name;

    switch (keyName) {
      case "q":
        requestExit();
        break;
      case "return":
      case "enter":
        handleCopySelected();
        break;
      case "m":
        dialog.openDialog("model-manager");
        break;
      case "s":
        dialog.openDialog("settings");
        break;
      case "h":
        dialog.openDialog("hotkey");
        break;
      case "t":
        dialog.openDialog("theme-picker");
        break;
      case "?":
        dialog.openDialog("welcome", { firstRun: false });
        break;
      case "up":
      case "k":
        transcriber.selectPrev();
        break;
      case "down":
      case "j":
        transcriber.selectNext();
        break;
    }
  });

  usePaste((event) => {
    if (shouldSuppressPasteInput()) {
      event.preventDefault();
      return;
    }
    if (dialog.isOpen()) return;
    const pasted = event.text.trim();
    if (!pasted) return;
    event.preventDefault();
    backend.send({ type: "transcribe_paste", text: pasted });
    toast.showToast("Paste received. Queueing transcription...");
  });

  function handleCopySelected() {
    const selected = transcriber.getSelected();
    if (!selected) {
      toast.showToast("No transcript selected");
      return;
    }
    transcriber.copyText(selected.text);
  }

  const modalOverlayColor = () => {
    const overlay = RGBA.fromHex(colors().backgroundOverlay);
    return RGBA.fromValues(overlay.r, overlay.g, overlay.b, colors().overlayAlpha);
  };

  function dismissDialogFromBackdrop(event: MouseEvent) {
    if (event.button !== 0) return;
    event.preventDefault();
    dialog.requestDismiss();
  }

  function stopModalMouseBubble(event: MouseEvent) {
    event.stopPropagation();
  }

  return (
    <box
      flexDirection="row"
      width="100%"
      height="100%"
      backgroundColor={colors().background}
    >
      <box
        flexDirection="row"
        flexGrow={1}
        height="100%"
        paddingTop={1}
        paddingBottom={1}
        paddingLeft={2}
        paddingRight={2}
      >
        <box
          width={1}
          borderStyle="single"
          border={["left"]}
          borderColor={activePane() === "main" ? colors().secondary : colors().borderSubtle}
          customBorderChars={{
            ...BorderChars.single,
            vertical: activePane() === "main" ? "┃" : "│",
          }}
        />
        <box
          flexDirection="column"
          flexGrow={1}
          height="100%"
          paddingLeft={1}
          gap={1}
        >
          <box flexShrink={0}>
            <Header onQuitClick={requestExit} />
          </box>
          <box flexGrow={1} flexShrink={1} height="100%">
            <TranscriptList />
          </box>
          <box flexShrink={0}>
            <Footer
              availableWidth={homePaneWidth()}
              onStatusClick={toggleRecordingFromStatusClick}
              onModelClick={() => dialog.openDialog("model-manager")}
              onHotkeyClick={() => dialog.openDialog("hotkey")}
              onLogsClick={toggleLogsPanel}
              onSettingsClick={() => dialog.openDialog("settings")}
              onThemeClick={() => dialog.openDialog("theme-picker")}
              onHelpClick={() => dialog.openDialog("welcome", { firstRun: false })}
            />
          </box>
        </box>
      </box>

      <Show when={logsVisible()}>
        <box
          width={LOGS_PANEL_WIDTH_COLS}
          height="100%"
          paddingLeft={2}
        >
          <box
            flexDirection="row"
            flexGrow={1}
            height="100%"
          >
            <box
              width={1}
              borderStyle="single"
              border={["left"]}
              borderColor={activePane() === "logs" ? colors().accent : colors().borderSubtle}
              customBorderChars={{
                ...BorderChars.single,
                vertical: activePane() === "logs" ? "┃" : "│",
              }}
            />
            <box flexGrow={1} height="100%" paddingLeft={1}>
              <LogPanel
                minLevel={LOG_LEVELS[logLevelIndex()]!}
                active={activePane() === "logs"}
              />
            </box>
          </box>
        </box>
      </Show>

      <Show when={dialog.currentDialog()?.type === "model-manager"}>
        <box
          position="absolute"
          width="100%"
          height="100%"
          justifyContent="center"
          alignItems="center"
          backgroundColor={modalOverlayColor()}
          onMouseUp={dismissDialogFromBackdrop}
        >
          <box onMouseUp={stopModalMouseBubble}>
            <ModelManager />
          </box>
        </box>
      </Show>

      <Show when={dialog.currentDialog()?.type === "settings"}>
        <box
          position="absolute"
          width="100%"
          height="100%"
          justifyContent="center"
          alignItems="center"
          backgroundColor={modalOverlayColor()}
          onMouseUp={dismissDialogFromBackdrop}
        >
          <box onMouseUp={stopModalMouseBubble}>
            <Settings />
          </box>
        </box>
      </Show>

      <Show when={dialog.currentDialog()?.type === "hotkey"}>
        <box
          position="absolute"
          width="100%"
          height="100%"
          justifyContent="center"
          alignItems="center"
          backgroundColor={modalOverlayColor()}
          onMouseUp={dismissDialogFromBackdrop}
        >
          <box onMouseUp={stopModalMouseBubble}>
            <HotkeyModal />
          </box>
        </box>
      </Show>

      <Show when={dialog.currentDialog()?.type === "settings-select"}>
        <box
          position="absolute"
          width="100%"
          height="100%"
          justifyContent="center"
          alignItems="center"
          backgroundColor={modalOverlayColor()}
          onMouseUp={dismissDialogFromBackdrop}
        >
          <box onMouseUp={stopModalMouseBubble}>
            <SettingsSelectModal />
          </box>
        </box>
      </Show>

      <Show when={dialog.currentDialog()?.type === "settings-edit"}>
        <box
          position="absolute"
          width="100%"
          height="100%"
          justifyContent="center"
          alignItems="center"
          backgroundColor={modalOverlayColor()}
          onMouseUp={dismissDialogFromBackdrop}
        >
          <box onMouseUp={stopModalMouseBubble}>
            <SettingsEditModal />
          </box>
        </box>
      </Show>

      <Show when={dialog.currentDialog()?.type === "theme-picker"}>
        <box
          position="absolute"
          width="100%"
          height="100%"
          justifyContent="center"
          alignItems="center"
          backgroundColor={modalOverlayColor()}
          onMouseUp={dismissDialogFromBackdrop}
        >
          <box onMouseUp={stopModalMouseBubble}>
            <ThemePickerModal />
          </box>
        </box>
      </Show>

      <Show when={dialog.currentDialog()?.type === "exit-confirm"}>
        <box
          position="absolute"
          width="100%"
          height="100%"
          justifyContent="center"
          alignItems="center"
          backgroundColor={modalOverlayColor()}
          onMouseUp={dismissDialogFromBackdrop}
        >
          <box onMouseUp={stopModalMouseBubble}>
            <ExitConfirmModal />
          </box>
        </box>
      </Show>

      <Show when={dialog.currentDialog()?.type === "runtime-switch-confirm"}>
        <box
          position="absolute"
          width="100%"
          height="100%"
          justifyContent="center"
          alignItems="center"
          backgroundColor={modalOverlayColor()}
          onMouseUp={dismissDialogFromBackdrop}
        >
          <box onMouseUp={stopModalMouseBubble}>
            <RuntimeSwitchConfirmModal />
          </box>
        </box>
      </Show>

      <Show when={dialog.currentDialog()?.type === "welcome"}>
        <box
          position="absolute"
          width="100%"
          height="100%"
          justifyContent="center"
          alignItems="center"
          backgroundColor={modalOverlayColor()}
          onMouseUp={dismissDialogFromBackdrop}
        >
          <box onMouseUp={stopModalMouseBubble}>
            <Welcome />
          </box>
        </box>
      </Show>

      <ToastContainer />
    </box>
  );
}
