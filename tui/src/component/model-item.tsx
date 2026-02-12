import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import type { ModelInfo } from "../types";

export interface ModelItemProps {
  model: ModelInfo;
  selected: boolean;
}

export function ModelItem(props: ModelItemProps): JSX.Element {
  const { colors } = useTheme();

  const bgColor = () =>
    props.selected ? colors().backgroundElement : undefined;

  const statusColor = () =>
    props.model.installed ? colors().success : colors().textDim;

  const statusIcon = () => (props.model.installed ? "●" : "○");

  return (
    <box
      paddingX={2}
      paddingY={0}
      backgroundColor={bgColor()}
    >
      <box flexDirection="row" width="100%">
        {/* Selection indicator */}
        <box width={2}>
          <text>
            <span fg={props.selected ? colors().primary : colors().textDim}>
              {props.selected ? "›" : " "}
            </span>
          </text>
        </box>

        {/* Model name */}
        <box flexGrow={1}>
          <text>
            <span fg={props.selected ? colors().text : colors().textMuted}>
              {props.model.name}
            </span>
          </text>
        </box>

        {/* Status */}
        <box width={12}>
          <text>
            <span fg={statusColor()}>
              {statusIcon()} {props.model.installed ? "installed" : "available"}
            </span>
          </text>
        </box>
      </box>
    </box>
  );
}
