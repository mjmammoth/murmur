import { For, Show, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useTranscriber } from "../context/transcriber";
import { TranscriptItem } from "./transcript-item";

export function TranscriptList(): JSX.Element {
  const { colors } = useTheme();
  const transcriber = useTranscriber();

  const count = () => transcriber.transcripts().length;

  return (
    <box
      flexGrow={1}
      flexDirection="column"
      backgroundColor={colors().backgroundPanel}
    >
      <box paddingX={2} paddingY={1}>
        <text>
          <span style={{ fg: colors().secondary }}>■</span>
          <span style={{ fg: colors().primary }}> Transcripts</span>
          <span style={{ fg: colors().textMuted }}> / {count()}</span>
        </text>
      </box>

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

      <Show when={transcriber.transcripts().length === 0}>
        <box
          flexGrow={1}
          justifyContent="center"
          alignItems="center"
          paddingY={2}
        >
          <box flexDirection="column" alignItems="center" gap={1}>
            <text>
              <span style={{ fg: colors().primary }}>*</span>
            </text>
            <text>
              <span style={{ fg: colors().text }}>No transcripts yet</span>
            </text>
            <text>
              <span style={{ fg: colors().textMuted }}>
                Press your hotkey to start recording
              </span>
            </text>
          </box>
        </box>
      </Show>
    </box>
  );
}
