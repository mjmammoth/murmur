import { createSignal, Show, type JSX } from "solid-js";
import { useKeyHandler } from "@opentui/solid";
import { RGBA, type KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
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
import { LogPanel } from "../component/log-panel";

export function Home(): JSX.Element {
  const { colors } = useTheme();
  const config = useConfig();
  const transcriber = useTranscriber();
  const dialog = useDialog();
  const toast = useToast();
  const [showLogs, setShowLogs] = createSignal(false);

  useKeyHandler((key: KeyEvent) => {
    // Log panel toggle works even with dialogs open
    if (key.name === "l" && !dialog.isOpen()) {
      setShowLogs((prev) => !prev);
      return;
    }

    if (dialog.isOpen()) return;

    const keyName = key.name;

    switch (keyName) {
      case "q":
        process.exit(0);
        break;
      case "c":
        handleCopyLatest();
        break;
      case "return":
      case "enter":
        handleCopySelected();
        break;
      case "y":
        config.toggleAutoCopy();
        break;
      case "n":
        config.toggleNoise();
        break;
      case "v":
        config.toggleVad();
        break;
      case "m":
        dialog.openDialog("model-manager");
        break;
      case "s":
        dialog.openDialog("settings");
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
      padding={2}
      gap={2}
    >
      <box flexDirection="column" flexGrow={1} height="100%" gap={2}>
        <Header />
        <TranscriptList />
        <Footer />
        <ToastContainer />
      </box>

      <Show when={showLogs()}>
        <box width="42%" height="100%">
          <LogPanel />
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
    </box>
  );
}
