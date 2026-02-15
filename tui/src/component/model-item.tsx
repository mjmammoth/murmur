import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import { useSpinnerFrame } from "./spinner";
import type { ModelInfo } from "../types";
import { formatBytes } from "../util/format";

const DOWNLOAD_SCANNER_WIDTH = 10;
const SCANNER_EMPTY = "⬝";
const SCANNER_MID = "▪";
const SCANNER_FULL = "■";

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

  const buildDownloadScanner = (percent: number) => {
    const clamped = Math.max(0, Math.min(100, Math.round(percent)));
    const progressCells = (clamped / 100) * DOWNLOAD_SCANNER_WIDTH;
    return Array.from({ length: DOWNLOAD_SCANNER_WIDTH }, (_, idx) => {
      const cellFill = progressCells - idx;
      if (cellFill >= 1) return SCANNER_FULL;
      if (cellFill >= 0.34) return SCANNER_MID;
      return SCANNER_EMPTY;
    }).join("");
  };

  const statusText = () => {
    const current = op();
    if (current) {
      if (current.type === "pulling") {
        const progress = backend.downloadProgress();
        if (progress && progress.model === props.model.name) {
          const percent = Math.max(0, Math.min(100, Math.round(progress.percent)));
          const percentLabel = `${percent}%`.padStart(4, " ");
          return `${spinnerFrame()} ${buildDownloadScanner(percent)} ${percentLabel}`;
        }
        return `${spinnerFrame()} pulling`;
      }
      return `${spinnerFrame()} removing`;
    }
    if (props.isSelectedModel) return "● selected";
    return props.model.installed ? "● pulled" : "○ not pulled";
  };

  const sizeLabel = () => {
    const size = props.model.size_bytes;
    if (typeof size !== "number" || size <= 0) return "";
    const prefix = props.model.size_estimated ? "~" : "";
    return ` ${prefix}${formatBytes(size)}`;
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
          <text>
            <span style={{ fg: mutedColor() }}>{props.model.name}</span>
            <span style={{ fg: colors().textDim }}>{sizeLabel()}</span>
          </text>
        </box>

        <box width={18}>
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
