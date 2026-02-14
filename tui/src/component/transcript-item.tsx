import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import type { TranscriptEntry } from "../types";

export interface TranscriptItemProps {
  entry: TranscriptEntry;
  selected: boolean;
  index: number;
  onClick?: () => void;
}

/**
 * Render a single transcript row with zebra striping and an optional selection indicator.
 *
 * Renders the entry timestamp and text, applies alternating background colors based on `index`,
 * and shows a vertical glyph when `selected` is true.
 *
 * @param props - Component properties describing the transcript entry and rendering state. `props.entry` is the entry to display, `props.index` controls zebra striping, `props.selected` toggles the selection indicator, and `props.onClick` (if provided) is invoked on mouse-up.
 * @returns A JSX element representing the rendered transcript row.
 */
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
      <box width={1} justifyContent="center" alignItems="center">
        <text>
          <span style={{ fg: props.selected ? colors().secondary : zebraBackground() }}>
            {props.selected ? "┃" : " "}
          </span>
        </text>
      </box>
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