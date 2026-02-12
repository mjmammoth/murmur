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
      borderStyle="rounded"
      borderColor={colors().border}
    >
      {/* Header */}
      <box paddingX={2} paddingY={1} borderStyle="single" border={["bottom"]} borderColor={colors().borderSubtle}>
        <text>
          <span fg={colors().primary}>~</span>
          <span fg={colors().text}> Logs</span>
          <span fg={colors().textDim}> ({backend.logs().length})</span>
        </text>
      </box>

      {/* Log entries */}
      <scrollbox flexGrow={1} stickyScroll stickyStart="bottom" paddingX={1}>
        <box flexDirection="column">
          <Show when={backend.logs().length === 0}>
            <box paddingY={1} paddingX={1}>
              <text fg={colors().textMuted}>No log entries yet</text>
            </box>
          </Show>
          <For each={backend.logs()}>
            {(entry: LogEntry) => (
              <box flexDirection="row" width="100%">
                <text>
                  <span fg={colors().textDim}>{entry.timestamp} </span>
                  <span fg={levelColor(entry.level, colors())}>{levelTag(entry.level)} </span>
                  <span fg={colors().textDim}>{entry.source}: </span>
                  <span fg={colors().text}>{entry.message}</span>
                </text>
              </box>
            )}
          </For>
        </box>
      </scrollbox>

      {/* Footer */}
      <box paddingX={2} paddingY={1} borderStyle="single" border={["top"]} borderColor={colors().borderSubtle}>
        <text>
          <span fg={colors().textDim}>[l]</span>
          <span fg={colors().textMuted}> close </span>
        </text>
      </box>
    </box>
  );
}
