import { Show, For, createSignal, onCleanup, type JSX } from "solid-js";
import { useTerminalDimensions } from "@opentui/solid";
import { useTheme } from "../context/theme";
import { useToast } from "../context/toast";
import { useBackend } from "../context/backend";

/**
 * Displays a top-right toast container showing current toast notifications.
 *
 * @returns The toast container JSX element
 */
export function ToastContainer(): JSX.Element {
  const { colors } = useTheme();
  const { toasts } = useToast();
  const backend = useBackend();
  const terminal = useTerminalDimensions();

  const toastWidth = () => {
    const available = Math.max(24, terminal().width - 6);
    return Math.min(46, available);
  };

  const [copiedToastId, setCopiedToastId] = createSignal<number | null>(null);
  const [copyAnnouncement, setCopyAnnouncement] = createSignal("");
  let copiedIndicatorTimer: ReturnType<typeof setTimeout> | null = null;

  function clearCopyFeedback() {
    setCopiedToastId(null);
    setCopyAnnouncement("");
    if (!copiedIndicatorTimer) return;
    clearTimeout(copiedIndicatorTimer);
    copiedIndicatorTimer = null;
  }

  function scheduleCopyFeedbackClear() {
    if (copiedIndicatorTimer) {
      clearTimeout(copiedIndicatorTimer);
    }
    copiedIndicatorTimer = setTimeout(() => {
      copiedIndicatorTimer = null;
      setCopiedToastId(null);
      setCopyAnnouncement("");
    }, 1000);
  }

  function handleToastCopy(toastId: number, message: string) {
    if (!backend.connected()) {
      setCopiedToastId(null);
      setCopyAnnouncement("Copy unavailable while disconnected");
      scheduleCopyFeedbackClear();
      return;
    }

    backend.send({ type: "copy_text", text: message });
    setCopiedToastId(toastId);
    setCopyAnnouncement("Copied toast message to clipboard");
    scheduleCopyFeedbackClear();
  }

  onCleanup(() => {
    clearCopyFeedback();
  });

  const getToastColor = (level: "info" | "error") => {
    switch (level) {
      case "error":
        return colors().error;
      case "info":
      default:
        return colors().success;
    }
  };

  return (
    <Show when={Boolean(copyAnnouncement()) || toasts().length > 0}>
      <box
        position="absolute"
        right={2}
        top={2}
        flexDirection="column"
        width={toastWidth()}
      >
        <For each={toasts()}>
          {(toast) => (
            <box
              flexDirection="row"
              marginBottom={1}
              backgroundColor={colors().backgroundPanel}
              paddingRight={2}
              paddingY={1}
              width="100%"
              onMouseUp={(event) => {
                if (event.button !== 0) return;
                handleToastCopy(toast.id, toast.message);
              }}
            >
              <box width={1} backgroundColor={getToastColor(toast.level)} />
              <box
                paddingLeft={1}
                flexDirection="column"
                flexGrow={1}
                flexShrink={1}
                width="100%"
              >
                <text>
                  <span style={{ fg: getToastColor(toast.level) }}>
                    {toast.level === "error" ? "error" : "info"}
                  </span>
                </text>
                <text wrapMode="word" width="100%">
                  <span style={{ fg: colors().text }}>{toast.message}</span>
                  <Show when={copiedToastId() === toast.id}>
                    <span style={{ fg: colors().accent, bold: true }}> copied</span>
                  </Show>
                </text>
              </box>
            </box>
          )}
        </For>
        <Show when={copyAnnouncement()}>
          <text aria-live="polite">
            <span style={{ fg: colors().textDim }}>{copyAnnouncement()}</span>
          </text>
        </Show>
      </box>
    </Show>
  );
}