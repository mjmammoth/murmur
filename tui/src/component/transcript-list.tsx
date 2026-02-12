import { For, Show, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useTranscriber } from "../context/transcriber";
import { TranscriptItem } from "./transcript-item";

export function TranscriptList(): JSX.Element {
  const { colors } = useTheme();
  const transcriber = useTranscriber();

  return (
    <box flexGrow={1} flexDirection="column">
      <scrollbox flexGrow={1} paddingX={1} stickyScroll stickyStart="bottom">
        <box flexDirection="column">
          <For each={transcriber.transcripts()}>
            {(entry, index) => (
              <TranscriptItem
                entry={entry}
                selected={index() === transcriber.selectedIndex()}
                index={index()}
              />
            )}
          </For>
        </box>
      </scrollbox>

      {/* Empty state */}
      <Show when={transcriber.transcripts().length === 0}>
        <box
          flexGrow={1}
          justifyContent="center"
          alignItems="center"
          paddingY={4}
        >
          <box flexDirection="column" alignItems="center">
            <text>
              <span fg={colors().textDim}>No transcripts yet</span>
            </text>
            <text>
              <span fg={colors().textMuted}>
                Press your hotkey to start recording
              </span>
            </text>
          </box>
        </box>
      </Show>
    </box>
  );
}
