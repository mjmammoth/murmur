import { Show, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useTranscriber } from "../context/transcriber";
import { useConfig } from "../context/config";
import { useSpinnerFrame } from "./spinner";

export function Header(): JSX.Element {
  const { colors } = useTheme();
  const transcriber = useTranscriber();
  const config = useConfig();
  const spinnerFrame = useSpinnerFrame();

  const statusColor = () => {
    const status = transcriber.status();
    switch (status) {
      case "recording":
        return colors().recording;
      case "transcribing":
      case "downloading":
        return colors().transcribing;
      case "error":
        return colors().error;
      case "ready":
        return colors().ready;
      default:
        return colors().textMuted;
    }
  };

  const statusIcon = () => {
    const status = transcriber.status();
    switch (status) {
      case "recording":
        return "●";
      case "ready":
        return "●";
      case "error":
        return "✗";
      default:
        return "";
    }
  };

  const statusDisplay = () => {
    if (transcriber.isBusy()) {
      const elapsed = transcriber.statusElapsed();
      const suffix = elapsed !== undefined ? ` (${elapsed}s)` : "";
      return `${spinnerFrame()} ${transcriber.statusMessage()}${suffix}`;
    }
    return `${statusIcon()} ${transcriber.statusMessage()}`;
  };

  const configInfo = () => {
    const cfg = config.config();
    if (!cfg) return null;
    return {
      model: cfg.model.name,
      hotkey: cfg.hotkey.key,
      mode: cfg.hotkey.mode,
    };
  };

  return (
    <box
      paddingX={2}
      paddingTop={1}
      paddingBottom={2}
      backgroundColor={colors().backgroundPanel}
    >
      <box flexDirection="row" justifyContent="space-between" width="100%">
        <box flexDirection="row" alignItems="center" gap={1}>
          <text>
            <span style={{ fg: colors().primary }}>whisper.local</span>
          </text>
          <text>
            <span style={{ fg: colors().textDim }}>/</span>
          </text>
          <text>
            <span style={{ fg: statusColor() }}>{statusDisplay()}</span>
          </text>
        </box>

        <Show when={configInfo()}>
          {(info) => (
            <box flexDirection="row" alignItems="center" gap={1}>
              <text>
                <span style={{ fg: colors().text }}>{info().model}</span>
              </text>
              <text>
                <span style={{ fg: colors().text }}>{info().hotkey}</span>
              </text>
              <text>
                <span style={{ fg: colors().textMuted }}>{info().mode}</span>
              </text>
            </box>
          )}
        </Show>
      </box>
    </box>
  );
}
