import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import type { TranscriptEntry } from "../types";

export interface TranscriptItemProps {
  entry: TranscriptEntry;
  selected: boolean;
  index: number;
}

export function TranscriptItem(props: TranscriptItemProps): JSX.Element {
  const { colors } = useTheme();

  const bgColor = () =>
    props.selected ? colors().backgroundElement : undefined;

  const fgColor = () =>
    props.selected ? colors().text : colors().text;

  const dimColor = () =>
    props.selected ? colors().textMuted : colors().textMuted;

  return (
    <box
      flexDirection="row"
      paddingRight={1}
      backgroundColor={bgColor()}
    >
      <box
        width={1}
        backgroundColor={props.selected ? colors().secondary : colors().borderSubtle}
      />
      <box flexDirection="row" width="100%">
        <box width={2}>
          <text>
            <span style={{ fg: props.selected ? colors().secondary : colors().textDim }}>
              {props.selected ? "•" : " "}
            </span>
          </text>
        </box>

        <box width={10}>
          <text>
            <span style={{ fg: dimColor() }}>{props.entry.timestamp}</span>
          </text>
        </box>

        <box flexGrow={1}>
          <text fg={fgColor()}>{props.entry.text}</text>
        </box>
      </box>
    </box>
  );
}
