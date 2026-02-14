import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import type { TranscriptEntry } from "../types";

export interface TranscriptItemProps {
  entry: TranscriptEntry;
  selected: boolean;
  index: number;
  onClick?: () => void;
}

export function TranscriptItem(props: TranscriptItemProps): JSX.Element {
  const { colors } = useTheme();

  const zebraBackground = () =>
    props.index % 2 === 0 ? colors().backgroundPanel : colors().backgroundElement;

  return (
    <box
      flexDirection="row"
      paddingRight={1}
      backgroundColor={zebraBackground()}
      onMouseUp={props.onClick}
    >
      <box
        width={1}
        backgroundColor={props.selected ? colors().secondary : zebraBackground()}
      />
      <box flexDirection="row" width="100%" paddingLeft={1}>
        <box width={10}>
          <text>
            <span style={{ fg: colors().textDim }}>{props.entry.timestamp}</span>
          </text>
        </box>

        <box flexGrow={1}>
          <text fg={colors().text}>{props.entry.text}</text>
        </box>
      </box>
    </box>
  );
}
