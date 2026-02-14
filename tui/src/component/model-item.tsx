import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import { useSpinnerFrame } from "./spinner";
import type { ModelInfo } from "../types";

export interface ModelItemProps {
  model: ModelInfo;
  selected: boolean;
}

export function ModelItem(props: ModelItemProps): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const spinnerFrame = useSpinnerFrame();

  const bgColor = () =>
    props.selected ? colors().backgroundElement : undefined;

  const fgColor = () =>
    props.selected ? colors().text : colors().text;

  const mutedColor = () =>
    props.selected ? colors().text : colors().textMuted;

  const op = () => {
    const active = backend.activeModelOp();
    return active && active.model === props.model.name ? active : null;
  };

  const statusColor = () => {
    if (props.selected) return colors().secondary;
    const current = op();
    if (current) {
      return current.type === "pulling" ? colors().transcribing : colors().warning;
    }
    return props.model.installed ? colors().success : colors().textDim;
  };

  const statusText = () => {
    const current = op();
    if (current) {
      if (current.type === "pulling") {
        const progress = backend.downloadProgress();
        if (progress && progress.model === props.model.name) {
          return `${spinnerFrame()} ${progress.percent}%`;
        }
        return `${spinnerFrame()} pulling`;
      }
      return `${spinnerFrame()} removing`;
    }
    return props.model.installed ? "● installed" : "○ available";
  };

  return (
    <box
      flexDirection="row"
      paddingRight={1}
      backgroundColor={bgColor()}
    >
      <box width={1} justifyContent="center" alignItems="center">
        <text>
          <span style={{ fg: props.selected ? colors().secondary : colors().borderSubtle }}>
            {props.selected ? "┃" : "│"}
          </span>
        </text>
      </box>
      <box flexDirection="row" width="100%">
        <box width={2}>
          <text>
            <span style={{ fg: props.selected ? colors().secondary : colors().textDim }}>
              {props.selected ? "•" : " "}
            </span>
          </text>
        </box>

        <box flexGrow={1}>
          <text fg={props.selected ? fgColor() : mutedColor()}>{props.model.name}</text>
        </box>

        <box width={14}>
          <text>
            <span style={{ fg: statusColor() }}>
              {statusText()}
            </span>
          </text>
        </box>
      </box>
    </box>
  );
}
