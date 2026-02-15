import { createEffect, createSignal, Show, type JSX } from "solid-js";
import { useKeyHandler, usePaste, useRenderer } from "@opentui/solid";
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
import { exitApp } from "../util/exit";

interface ModelManagerDialogData {
  firstRunSetup?: boolean;
}

export function Home(): JSX.Element {
  const { colors } = useTheme();
  const renderer = useRenderer();
  const backend = useBackend();
  const config = useConfig();
  const transcriber = useTranscriber();
  const dialog = useDialog();
  const toast = useToast();
  const [showLogs, setShowLogs] = createSignal(false);
  const [activePane, setActivePane] = createSignal<"main" | "logs">("main");
  const [logLevelIndex, setLogLevelIndex] = createSignal(1);
  const firstRunSetupRequired = () => Boolean(backend.config()?.first_run_setup_required);

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

  useKeyHandler((key: KeyEvent) => {
    if (key.ctrl && key.name === "c") {
      key.preventDefault();
      exitApp(renderer);
      return;
    }

    // Log panel toggle works even with dialogs open
    if (key.name === "l" && !dialog.isOpen()) {
      setShowLogs((prev) => {
        const next = !prev;
        setActivePane(next ? "logs" : "main");
        return next;
      });
      return;
    }

    if (key.name === "escape" && showLogs() && !dialog.isOpen()) {
      setShowLogs(false);
      setActivePane("main");
      return;
    }

    if (key.name === "tab" && showLogs() && !dialog.isOpen()) {
      key.preventDefault();
      setActivePane((pane) => (pane === "main" ? "logs" : "main"));
      return;
    }

    if (
      showLogs() &&
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

    if (showLogs() && activePane() === "logs") {
      if (key.name === "up" || key.name === "down" || key.name === "j" || key.name === "k") {
        return;
      }
    }

    const keyName = key.name;

    switch (keyName) {
      case "q":
        exitApp(renderer);
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
            <Footer />
          </box>
          <ToastContainer />
        </box>
      </box>

      <Show when={showLogs()}>
        <box
          width="42%"
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
    </box>
  );
}
