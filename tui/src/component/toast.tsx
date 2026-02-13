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
        width={46}
      >
        <For each={toasts()}>
          {(toast) => (
            <box
              flexDirection="row"
              marginBottom={1}
              backgroundColor={colors().backgroundPanel}
              paddingRight={2}
              paddingY={1}
            >
              <box width={1} backgroundColor={getToastColor(toast.level)} />
              <box paddingLeft={1}>
                <text>
                  <span style={{ fg: getToastColor(toast.level) }}>
                    {toast.level === "error" ? "error" : "info"}
                  </span>
                  <span style={{ fg: colors().textMuted }}> / </span>
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
