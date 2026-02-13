import { createEffect, createSignal, Show, type JSX } from "solid-js";
import { useKeyHandler, useRenderer } from "@opentui/solid";
import { RGBA, type KeyEvent } from "@opentui/core";
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

  createEffect(() => {
    backend.send({ type: "set_hotkey_blocked", enabled: dialog.isOpen() });
  });

  function exitApp() {
    try {
      renderer.destroy();
    } catch {
      // Ignore renderer teardown errors during exit
    }

    try {
      if (process.stdin.isTTY && "setRawMode" in process.stdin) {
        (process.stdin as NodeJS.ReadStream).setRawMode(false);
      }
    } catch {
      // Ignore raw mode reset errors during exit
    }

    try {
      // Disable common mouse tracking modes and restore cursor/style.
      process.stdout.write("\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l\x1b[?25h\x1b[0m");
    } catch {
      // Ignore terminal restore write errors during exit
    }

    process.exit(0);
  }

  useKeyHandler((key: KeyEvent) => {
    if (key.ctrl && key.name === "c") {
      key.preventDefault();
      exitApp();
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
        exitApp();
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
        <Show when={showLogs()}>
          <box
            width={1}
            borderStyle="single"
            border={["left"]}
            borderColor={activePane() === "main" ? colors().secondary : colors().borderSubtle}
          />
        </Show>
        <box
          flexDirection="column"
          flexGrow={1}
          height="100%"
          paddingLeft={showLogs() ? 1 : 0}
          gap={1}
        >
          <Header />
          <TranscriptList />
          <Footer />
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
            flexGrow={1}
            height="100%"
            paddingLeft={1}
            borderStyle="single"
            border={["left"]}
            borderColor={activePane() === "logs" ? colors().secondary : colors().borderSubtle}
          >
            <LogPanel
              minLevel={LOG_LEVELS[logLevelIndex()]!}
              active={activePane() === "logs"}
            />
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
          backgroundColor={RGBA.fromInts(0, 0, 0, 160)}
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
          backgroundColor={RGBA.fromInts(0, 0, 0, 160)}
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
          backgroundColor={RGBA.fromInts(0, 0, 0, 160)}
        >
          <HotkeyModal />
        </box>
      </Show>
    </box>
  );
}
