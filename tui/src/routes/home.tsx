import { createEffect, createSignal, Show, type JSX } from "solid-js";
import { useKeyHandler, usePaste, useRenderer, useTerminalDimensions } from "@opentui/solid";
import { BorderChars, RGBA, type KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import { useConfig } from "../context/config";
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
import { exitApp } from "../util/exit";
import type { ModelManagerDialogData } from "../types";

/**
 * Renders the main application Home screen, coordinating the primary transcript pane, optional logs panel, keyboard shortcuts, paste handling, backend interactions, and modal dialogs.
 *
 * The component manages UI state (logs visibility, active pane, log level), subscribes to backend and terminal dimension changes, handles global hotkeys and paste events, and conditionally renders modal overlays such as model manager, settings, hotkey/help, theme picker, and exit confirmation.
 *
 * @returns The root JSX element for the Home screen layout containing the header, transcript list, footer, optional logs panel, toast container, and modal overlays. 
 */
export function Home(): JSX.Element {
  const LOGS_PANEL_WIDTH_COLS = 48;
  const LOGS_PANEL_MIN_TERMINAL_WIDTH = 115;
  const { colors } = useTheme();
  const renderer = useRenderer();
  const terminal = useTerminalDimensions();
  const backend = useBackend();
  const config = useConfig();
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

  createEffect(() => {
    if (!logsVisible() && activePane() === "logs") {
      setActivePane("main");
    }
  });

  let previousLogsVisible = false;
  createEffect(() => {
    const currentlyVisible = logsVisible();
    if (previousLogsVisible && !currentlyVisible && showLogs() && !canShowLogs()) {
      toast.showToast(logsTooNarrowMessage());
    }
    previousLogsVisible = currentlyVisible;
  });

  createEffect(() => {
    if (!backend.connected()) return;
    backend.send({ type: "list_models" });
  });

  createEffect(() => {
    if (!firstRunSetupRequired()) return;
    const models = backend.models();
    if (models.length === 0) return;

    const currentDialog = dialog.currentDialog();
    const currentData = (currentDialog?.data as ModelManagerDialogData | undefined) ?? undefined;
    if (currentDialog?.type === "model-manager" && currentData?.firstRunSetup) {
      return;
    }

    dialog.openDialog("model-manager", { firstRunSetup: true });
  });

  createEffect(() => {
    backend.send({ type: "set_hotkey_blocked", enabled: dialog.isOpen() });
  });

  function requestExit() {
    const activeOp = backend.activeModelOp();
    const currentDialog = dialog.currentDialog();
    if (activeOp?.type === "pulling" && currentDialog?.type !== "exit-confirm") {
      dialog.openDialog("exit-confirm", { model: activeOp.model });
      return;
    }
    exitApp(renderer);
  }

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
      setShowLogs((prev) => {
        const next = !prev;
        if (next && !canShowLogs()) {
          toast.showToast(logsTooNarrowMessage());
        }
        setActivePane(next && canShowLogs() ? "logs" : "main");
        return next;
      });
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
      case "c":
        handleCopyLatest();
        break;
      case "return":
      case "enter":
        handleCopySelected();
        break;
      case "a":
        config.toggleAutoCopy();
        break;
      case "p":
        config.toggleAutoPaste();
        break;
      case "n":
        config.toggleNoise();
        break;
      case "v":
        config.toggleVad();
        break;
      case "o":
        config.toggleHotkeyMode();
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

  function handleCopyLatest() {
    const latest = transcriber.getLatest();
    if (!latest) {
      toast.showToast("No transcripts yet");
      return;
    }
    transcriber.copyText(latest.text);
  }

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
            <Header />
          </box>
          <box flexGrow={1} flexShrink={1} height="100%">
            <TranscriptList />
          </box>
          <box flexShrink={0}>
            <Footer availableWidth={homePaneWidth()} />
          </box>
          <ToastContainer />
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
              borderColor={activePane() === "logs" ? colors().secondary : colors().borderSubtle}
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
        >
          <ModelManager />
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
        >
          <Settings />
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
        >
          <HotkeyModal />
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
        >
          <SettingsSelectModal />
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
        >
          <SettingsEditModal />
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
        >
          <ThemePickerModal />
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
        >
          <ExitConfirmModal />
        </box>
      </Show>
    </box>
  );
}