import { createMemo, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import { useSpinnerFrame } from "./spinner";
import type { RuntimeName, ModelInfo } from "../types";
import { formatBytes, truncate } from "../util/format";

export const MODEL_TABLE_LAYOUT = {
  rowPrefix: 0,
  model: 16,
  separator: 1,
  size: 14,
  runtime: 14,
} as const;

interface RuntimeStatusToken {
  text: string;
  color: string;
}

export interface ModelItemProps {
  model: ModelInfo;
  selected: boolean;
  isSelectedModel: boolean;
  onClick?: () => void;
}

export function ModelItem(props: ModelItemProps): JSX.Element {
  const { colors, themeId } = useTheme();
  const backend = useBackend();
  const spinnerFrame = useSpinnerFrame();

  function selectedRowSubtleColor(): string {
    switch (themeId()) {
      case "dark":
        return "#1f3a2f";
      case "light":
        return "#d7efe3";
      case "catppuccin-mocha":
        return "#243a31";
      case "catppuccin-latte":
        return "#cadfce";
      default:
        return colors().backgroundHighlight;
    }
  }

  function selectedRowBrightColor(): string {
    switch (themeId()) {
      case "dark":
        return "#2b4d3f";
      case "light":
        return "#b8ddca";
      case "catppuccin-mocha":
        return "#315146";
      case "catppuccin-latte":
        return "#afd0ba";
      default:
        return colors().backgroundElement;
    }
  }

  const bgColor = () => {
    if (props.isSelectedModel) {
      return props.selected ? selectedRowBrightColor() : selectedRowSubtleColor();
    }
    return props.selected ? colors().backgroundElement : undefined;
  };

  const mutedColor = () =>
    props.selected || props.isSelectedModel ? colors().text : colors().textMuted;

  const op = () => {
    const active = backend.activeModelOp();
    return active && active.model === props.model.name ? active : null;
  };

  const activeRuntime = () =>
    (backend.config()?.model.runtime as RuntimeName | undefined) ?? "faster-whisper";

  const sizeLabel = () => {
    const activeVariant = props.model.variants[activeRuntime()];
    const size = activeVariant?.size_bytes;
    if (typeof size !== "number" || size <= 0) return "-";

    const prefix = activeVariant?.size_estimated ? "~" : "";
    return `${prefix}${formatBytes(size)}`;
  };

  const alignedSizeLabel = () => sizeLabel().padStart(MODEL_TABLE_LAYOUT.size, " ");

  const runtimeToken = (): RuntimeStatusToken => {
    const runtime = activeRuntime();
    const variant = props.model.variants[runtime];
    const current = op();
    if (current?.runtime === runtime) {
      if (current.type === "pulling") {
        const progress = backend.downloadProgress();
        if (
          progress &&
          progress.model === props.model.name &&
          progress.runtime === runtime
        ) {
          const percent = Math.max(0, Math.min(100, Math.round(progress.percent)));
          return { text: `${spinnerFrame()}${percent}%`, color: colors().transcribing };
        }
        return { text: `${spinnerFrame()}pull`, color: colors().transcribing };
      }
      return { text: `${spinnerFrame()}rm`, color: colors().warning };
    }
    if (backend.isModelPullQueued(props.model.name, runtime)) {
      return { text: "queued", color: colors().accent };
    }
    if (variant?.installed) {
      return { text: "●", color: colors().secondary };
    }
    return { text: "○", color: colors().textDim };
  };

  const statusToken = createMemo(runtimeToken);
  const separatorColor = () => {
    if (props.selected) return colors().secondary;
    if (props.isSelectedModel) return colors().success;
    return colors().borderSubtle;
  };

  return (
    <box
      flexDirection="row"
      backgroundColor={bgColor()}
      onMouseUp={props.onClick}
    >
      <box
        width={1}
        backgroundColor={props.selected ? colors().secondary : undefined}
      />
      <box width={MODEL_TABLE_LAYOUT.rowPrefix - 1} />
      <box flexDirection="row" width="100%">
        <box width={MODEL_TABLE_LAYOUT.model}>
          <text>
            <span style={{ fg: mutedColor() }}>
              {truncate(props.model.name, MODEL_TABLE_LAYOUT.model - 1)}
            </span>
          </text>
        </box>
        <box width={MODEL_TABLE_LAYOUT.separator} justifyContent="center">
          <text>
            <span style={{ fg: separatorColor() }}>┃</span>
          </text>
        </box>
        <box width={MODEL_TABLE_LAYOUT.size}>
          <text>
            <span style={{ fg: colors().textDim }}>
              {truncate(alignedSizeLabel(), MODEL_TABLE_LAYOUT.size)}
            </span>
          </text>
        </box>
        <box width={MODEL_TABLE_LAYOUT.separator} justifyContent="center">
          <text>
            <span style={{ fg: separatorColor() }}>┃</span>
          </text>
        </box>
        <box width={MODEL_TABLE_LAYOUT.runtime} justifyContent="center" alignItems="center">
          <text>
            <span style={{ fg: statusToken().color }}>{statusToken().text}</span>
          </text>
        </box>
      </box>
    </box>
  );
}
