import { For, Show, createMemo, type JSX } from "solid-js";
import { useKeyHandler } from "@opentui/solid";
import type { KeyEvent, ScrollBoxRenderable } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import type { LogEntry } from "../types";

export const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;
export type LogLevelName = (typeof LOG_LEVELS)[number];

interface LogPanelProps {
  minLevel: LogLevelName;
  active: boolean;
}

function levelRank(level: string): number {
  const idx = LOG_LEVELS.indexOf(level.toUpperCase() as LogLevelName);
  return idx >= 0 ? idx : 1;
}

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

function normalizeLogLines(message: string): string[] {
  const withoutAnsi = message.replaceAll(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, "");
  const normalizedNewlines = withoutAnsi.replaceAll(/\r\n?/g, "\n");
  const withoutControls = normalizedNewlines.replaceAll(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "");
  const lines = withoutControls
    .split("\n")
    .map((line) => line.replaceAll(/\t/g, "  ").trimEnd());

  if (lines.length === 0) return [""];
  if (lines.every((line) => line.length === 0)) return [""];
  return lines;
}

/**
 * Renders the log panel UI for viewing and interacting with backend log entries.
 *
 * The panel displays a header with the current minimum log level and count, a scrollable
 * list of backend logs filtered by `props.minLevel`, and a footer with keyboard hints.
 * While `props.active` is true the panel accepts keyboard navigation (arrow keys, j/k,
 * page up/down, home/end) to scroll the view. Clicking a log entry sends a `copy_text`
 * event to the backend with the selected entry's formatted text.
 *
 * @param props - Component props controlling the panel (see LogPanelProps). `minLevel` sets the minimum log level to show; `active` enables keyboard interaction.
 * @returns The rendered log panel as a JSX element.
 */
export function LogPanel(props: LogPanelProps): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  let logScroll: ScrollBoxRenderable | undefined;

  useKeyHandler((key: KeyEvent) => {
    if (!props.active || !logScroll || logScroll.isDestroyed) return;

    switch (key.name) {
      case "up":
      case "k":
        key.preventDefault();
        logScroll.scrollBy(-1, "step");
        break;
      case "down":
      case "j":
        key.preventDefault();
        logScroll.scrollBy(1, "step");
        break;
      case "pageup":
        key.preventDefault();
        logScroll.scrollBy(-1, "viewport");
        break;
      case "pagedown":
        key.preventDefault();
        logScroll.scrollBy(1, "viewport");
        break;
      case "home":
        key.preventDefault();
        logScroll.scrollTo(0);
        break;
      case "end":
        key.preventDefault();
        logScroll.scrollTo(logScroll.scrollHeight);
        break;
    }
  });

  const filteredLogs = createMemo(() => {
    const minRank = levelRank(props.minLevel);
    return backend.logs().filter((entry) => levelRank(entry.level) >= minRank);
  });

  return (
    <box
      flexDirection="column"
      width="100%"
      height="100%"
      backgroundColor={colors().backgroundPanel}
      paddingTop={1}
      paddingBottom={1}
      paddingRight={1}
    >
      <box paddingX={2} paddingTop={0} paddingBottom={0} flexDirection="column" flexShrink={0}>
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>Logs</span>
          </text>
          <box flexDirection="row" alignItems="center" gap={2} paddingLeft={1} flexShrink={1}>
            <text>
              <span style={{ fg: colors().textMuted }}>{filteredLogs().length} logs</span>
            </text>
            <text>
              <span style={{ fg: colors().textMuted }}>level </span>
              <span style={{ fg: levelColor(props.minLevel, colors()) }}>{props.minLevel}</span>
            </text>
          </box>
        </box>
        <box flexDirection="row" width="100%" marginTop={0}>
          <box width={3} borderStyle="single" border={["bottom"]} borderColor={colors().accent} />
          <box flexGrow={1} borderStyle="single" border={["bottom"]} borderColor={colors().borderSubtle} />
        </box>
      </box>

      <scrollbox
        flexGrow={1}
        flexShrink={1}
        paddingX={1}
        ref={(r) => {
          logScroll = r;
        }}
      >
        <box flexDirection="column">
          <Show when={filteredLogs().length === 0}>
            <box paddingY={1} paddingX={1}>
              <text fg={colors().textMuted}>No log entries at this level</text>
            </box>
          </Show>
          <For each={filteredLogs()}>
            {(entry: LogEntry, index) => {
              const lines = normalizeLogLines(entry.message);
              const blockText = `${entry.timestamp} ${levelTag(entry.level)} ${entry.source}:\n${lines.join("\n")}`;
              const rowBackground = () =>
                index() % 2 === 0 ? colors().backgroundPanel : colors().backgroundElement;

              return (
                <box
                  flexDirection="column"
                  width="100%"
                  paddingX={1}
                  paddingY={1}
                  backgroundColor={rowBackground()}
                  onMouseUp={() => {
                    backend.send({ type: "copy_text", text: blockText });
                  }}
                >
                  <text>
                    <span style={{ fg: colors().textDim }}>{entry.timestamp} </span>
                    <span style={{ fg: levelColor(entry.level, colors()) }}>{levelTag(entry.level)} </span>
                    <span style={{ fg: colors().textDim }}>{entry.source}</span>
                  </text>
                  <For each={lines}>
                    {(line) => (
                      <box paddingLeft={2}>
                        <text>
                          <span style={{ fg: colors().text }}>{line || " "}</span>
                        </text>
                      </box>
                    )}
                  </For>
                </box>
              );
            }}
          </For>
        </box>
      </scrollbox>

      <box paddingX={2} paddingY={1} flexShrink={0}>
        <text>
          <span style={{ fg: colors().text }}>l</span>
          <span style={{ fg: colors().textMuted }}> close </span>
          <span style={{ fg: colors().text }}>tab</span>
          <span style={{ fg: colors().textMuted }}> focus </span>
          <span style={{ fg: colors().text }}>click</span>
          <span style={{ fg: colors().textMuted }}> copy </span>
          <span style={{ fg: colors().text }}>↑/↓ j/k</span>
          <span style={{ fg: colors().textMuted }}> scroll </span>
          <span style={{ fg: colors().text }}>←/→</span>
          <span style={{ fg: colors().textMuted }}> level</span>
        </text>
      </box>
    </box>
  );
}
