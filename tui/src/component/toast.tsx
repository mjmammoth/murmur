import { Show, For, type JSX } from "solid-js";
import { useTerminalDimensions } from "@opentui/solid";
import { useTheme } from "../context/theme";
import { useToast } from "../context/toast";

/**
 * Renders a top-right toast container that displays current toast notifications.
 *
 * The container is visible only when there are toasts and its width is constrained by terminal dimensions. Each toast shows a colored level indicator ("error" or "info") and the message text.
 *
 * @returns The rendered toast container element
 */
export function ToastContainer(): JSX.Element {
  const { colors } = useTheme();
  const { toasts } = useToast();
  const terminal = useTerminalDimensions();

  const toastWidth = () => {
    const available = Math.max(24, terminal().width - 6);
    return Math.min(46, available);
  };

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
    <Show when={toasts().length > 0}>
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
                </text>
              </box>
            </box>
          )}
        </For>
      </box>
    </Show>
  );
}