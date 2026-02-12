import { Show, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useTranscriber } from "../context/transcriber";
import { useConfig } from "../context/config";
import { useBackend } from "../context/backend";
import { Spinner } from "./spinner";

export function Header(): JSX.Element {
  const { colors } = useTheme();
  const transcriber = useTranscriber();
  const config = useConfig();
  const backend = useBackend();

  const statusColor = () => {
    const status = transcriber.status();
    switch (status) {
      case "recording":
        return colors().recording;
      case "transcribing":
      case "downloading":
        return colors().transcribing;
      case "ready":
        return colors().ready;
      case "error":
        return colors().error;
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
        return "○";
    }
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
      paddingY={1}
      backgroundColor={colors().backgroundPanel}
      borderStyle="rounded"
      borderColor={colors().borderSubtle}
    >
      <box flexDirection="row" justifyContent="space-between" width="100%">
        {/* Left side - Status */}
        <box flexDirection="row" alignItems="center">
          <Show
            when={!transcriber.isBusy()}
            fallback={
              <Spinner
                label={transcriber.statusMessage()}
                color={statusColor()}
              />
            }
          >
            <text>
              <span fg={statusColor()}>{statusIcon()}</span>
              <span fg={colors().text}> {transcriber.statusMessage()}</span>
            </text>
          </Show>

          <Show when={transcriber.statusElapsed() !== undefined && transcriber.isBusy()}>
            <text fg={colors().textDim}> ({transcriber.statusElapsed()}s)</text>
          </Show>
        </box>

        {/* Right side - Config info */}
        <Show when={configInfo()}>
          {(info) => (
            <box flexDirection="row">
              <text>
                <span fg={colors().textDim}>model:</span>
                <span fg={colors().text}>{info().model}</span>
                <span fg={colors().textDim}> │ </span>
                <span fg={colors().textDim}>hotkey:</span>
                <span fg={colors().accent}>{info().hotkey}</span>
                <span fg={colors().textDim}> ({info().mode})</span>
              </text>
            </box>
          )}
        </Show>
      </box>
    </box>
  );
}
