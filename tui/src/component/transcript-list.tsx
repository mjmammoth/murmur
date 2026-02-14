import { For, Show, type JSX } from "solid-js";
import { useTerminalDimensions } from "@opentui/solid";
import { useTheme } from "../context/theme";
import { useTranscriber } from "../context/transcriber";
import { TranscriptItem } from "./transcript-item";

export function TranscriptList(): JSX.Element {
  const { colors } = useTheme();
  const transcriber = useTranscriber();
  const terminal = useTerminalDimensions();

  const count = () => transcriber.transcripts().length;
  const countLabel = () => {
    const n = count();
    return `${n} ${n === 1 ? "item" : "items"}`;
  };

  const emptyStateMode = (): "full" | "compact" | "icon" => {
    const h = terminal().height;
    if (h >= 22) return "full";
    if (h >= 16) return "compact";
    return "icon";
  };

  return (
    <box
      flexGrow={1}
      flexShrink={1}
      flexDirection="column"
      backgroundColor={colors().backgroundPanel}
    >
      <box paddingX={2} paddingTop={1} paddingBottom={0} flexDirection="column" flexShrink={0}>
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>Transcripts</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>{countLabel()}</span>
          </text>
        </box>
        <box flexDirection="row" width="100%" marginTop={0}>
          <box width={3} borderStyle="single" border={["bottom"]} borderColor={colors().secondary} />
          <box flexGrow={1} borderStyle="single" border={["bottom"]} borderColor={colors().borderSubtle} />
        </box>
      </box>

      <Show
        when={count() > 0}
        fallback={
          <box
            flexGrow={1}
            flexShrink={1}
            justifyContent="center"
            alignItems="center"
            paddingY={emptyStateMode() === "full" ? 2 : 0}
            paddingX={2}
          >
            <box
              flexDirection="column"
              alignItems="center"
              gap={emptyStateMode() === "full" ? 1 : 0}
            >
              <text>
                <span style={{ fg: colors().primary }}>*</span>
              </text>
              <Show when={emptyStateMode() !== "icon"}>
                <text>
                  <span style={{ fg: colors().text }}>No transcripts yet</span>
                </text>
              </Show>
              <Show when={emptyStateMode() === "full"}>
                <text>
                  <span style={{ fg: colors().textMuted }}>Press your hotkey to start recording</span>
                </text>
              </Show>
            </box>
          </box>
        }
      >
        <scrollbox flexGrow={1} flexShrink={1} paddingX={1} stickyScroll stickyStart="bottom">
          <box flexDirection="column">
            <For each={transcriber.transcripts()}>
              {(entry, index) => (
                <TranscriptItem
                  entry={entry}
                  selected={index() === transcriber.selectedIndex()}
                  index={index()}
                  onClick={() => {
                    transcriber.selectIndex(index());
                    transcriber.copyText(entry.text);
                  }}
                />
              )}
            </For>
          </box>
        </scrollbox>
      </Show>
    </box>
  );
}
