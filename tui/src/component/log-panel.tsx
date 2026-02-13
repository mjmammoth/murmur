import { For, Show, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import type { LogEntry } from "../types";

function levelColor(level: string, colors: ReturnType<ReturnType<typeof useTheme>["colors"]>): string {
  switch (level.toUpperCase()) {
    case "ERROR":
    case "CRITICAL":
      return colors.error;
    case "WARNING":
      return colors.warning;
    case "INFO":
      return colors.accent;
    case "DEBUG":
      return colors.textDim;
    default:
      return colors.textMuted;
  }
}

function levelTag(level: string): string {
  switch (level.toUpperCase()) {
    case "ERROR": return "ERR";
    case "CRITICAL": return "CRT";
    case "WARNING": return "WRN";
    case "INFO": return "INF";
    case "DEBUG": return "DBG";
    default: return level.slice(0, 3).toUpperCase();
  }
}

export function LogPanel(): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();

  return (
    <box
      flexDirection="column"
      width="100%"
      height="100%"
      backgroundColor={colors().backgroundPanel}
    >
      <box paddingX={2} paddingY={1}>
        <text>
          <span style={{ fg: colors().secondary }}>■</span>
          <span style={{ fg: colors().primary }}> Logs</span>
          <span style={{ fg: colors().textMuted }}> / {backend.logs().length} entries</span>
        </text>
      </box>

      <scrollbox flexGrow={1} stickyScroll stickyStart="bottom" paddingX={1}>
        <box flexDirection="column">
          <Show when={backend.logs().length === 0}>
            <box paddingY={1} paddingX={1}>
              <text fg={colors().textMuted}>No log entries yet</text>
            </box>
          </Show>
          <For each={backend.logs()}>
            {(entry: LogEntry) => (
              <box flexDirection="row" width="100%" paddingX={1}>
                <text>
                  <span style={{ fg: colors().textDim }}>{entry.timestamp} </span>
                  <span style={{ fg: levelColor(entry.level, colors()) }}>{levelTag(entry.level)} </span>
                  <span style={{ fg: colors().textDim }}>{entry.source}: </span>
                  <span style={{ fg: colors().text }}>{entry.message}</span>
                </text>
              </box>
            )}
          </For>
        </box>
      </scrollbox>

      <box paddingX={2} paddingY={1}>
        <text>
          <span style={{ fg: colors().text }}>l</span>
          <span style={{ fg: colors().textMuted }}> close</span>
        </text>
      </box>
    </box>
  );
}
