import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import { useSpinnerFrame } from "./spinner";
import type { ModelInfo } from "../types";

export interface ModelItemProps {
  model: ModelInfo;
  selected: boolean;
  isSelectedModel: boolean;
}

export function ModelItem(props: ModelItemProps): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const spinnerFrame = useSpinnerFrame();

  const bgColor = () =>
    props.selected ? colors().backgroundElement : undefined;

  const mutedColor = () =>
    props.selected ? colors().text : colors().textMuted;

  const op = () => {
    const active = backend.activeModelOp();
    return active && active.model === props.model.name ? active : null;
  };

  const statusColor = () => {
    const current = op();
    if (current) {
      return current.type === "pulling" ? colors().transcribing : colors().warning;
    }
    if (props.isSelectedModel) return colors().secondary;
    return props.model.installed ? colors().success : colors().textDim;
  };

  const statusText = () => {
    const current = op();
    if (current) {
      if (current.type === "pulling") {
        const progress = backend.downloadProgress();
        if (progress && progress.model === props.model.name) {
          const percent = Math.max(0, Math.min(100, Math.round(progress.percent)));
          if (percent >= 100) {
            return `${spinnerFrame()} finalizing`;
          }
          return `${spinnerFrame()} ${percent}%`;
        }
        return `${spinnerFrame()} pulling`;
      }
      return `${spinnerFrame()} removing`;
    }
    if (props.isSelectedModel) return "● selected";
    return props.model.installed ? "● pulled" : "○ not pulled";
  };

  return (
    <box
      flexDirection="row"
      paddingRight={1}
      backgroundColor={bgColor()}
    >
      <box
        width={1}
        backgroundColor={props.selected ? colors().secondary : undefined}
      />
      <box flexDirection="row" width="100%" paddingLeft={1}>
        <box flexGrow={1}>
          <text fg={mutedColor()}>{props.model.name}</text>
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
