import { Show, For, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useToast } from "../context/toast";

export function ToastContainer(): JSX.Element {
  const { colors } = useTheme();
  const { toasts } = useToast();

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
        width={40}
      >
        <For each={toasts()}>
          {(toast) => (
            <box
              marginBottom={1}
              backgroundColor={colors().backgroundPanel}
              borderStyle="single"
              border={["left", "right"]}
              borderColor={getToastColor(toast.level)}
              paddingX={2}
              paddingY={0}
            >
              <text>
                <span fg={getToastColor(toast.level)}>
                  {toast.level === "error" ? "✗" : "✓"}
                </span>
                <span fg={colors().text}> {toast.message}</span>
              </text>
            </box>
          )}
        </For>
      </box>
    </Show>
  );
}
