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

  const borderColor = () =>
    props.selected ? colors().primary : colors().borderSubtle;

  return (
    <box
      paddingX={2}
      paddingY={0}
      marginY={0}
      backgroundColor={bgColor()}
      borderStyle="single"
      border={["left"]}
      borderColor={borderColor()}
    >
      <box flexDirection="row" width="100%">
        {/* Timestamp */}
        <box width={10}>
          <text>
            <span fg={colors().textDim}>{props.entry.timestamp}</span>
          </text>
        </box>

        {/* Separator */}
        <box width={3}>
          <text>
            <span fg={colors().borderSubtle}>│</span>
          </text>
        </box>

        {/* Content */}
        <box flexGrow={1}>
          <text>
            <span fg={props.selected ? colors().text : colors().textMuted}>
              {props.entry.text}
            </span>
          </text>
        </box>
      </box>
    </box>
  );
}
