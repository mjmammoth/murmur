import { type JSX } from "solid-js";
import { useTerminalDimensions } from "@opentui/solid";
import { useTheme } from "../context/theme";
import { useConfig } from "../context/config";
import { useTranscriber } from "../context/transcriber";
import { Scanner } from "./spinner";

interface KeyHintProps {
  keyChar: string;
  word: string;
}

interface PairHintProps {
  label: string;
  value: string;
  keyChar?: string;
  highlightColor?: string;
}

function KeyHint(props: KeyHintProps): JSX.Element {
  const { colors } = useTheme();
  const idx = Math.max(0, props.word.toLowerCase().indexOf(props.keyChar.toLowerCase()));
  const before = props.word.slice(0, idx);
  const key = props.word[idx] ?? props.keyChar;
  const after = props.word.slice(idx + 1);

  return (
    <text>
      <span style={{ fg: colors().textMuted }}>{before}</span>
      <span style={{ fg: colors().accent, bold: true }}>{key}</span>
      <span style={{ fg: colors().textMuted }}>{after}</span>
    </text>
  );
}

function PairHint(props: PairHintProps): JSX.Element {
  const { colors } = useTheme();
  const idx = props.keyChar
    ? Math.max(0, props.label.toLowerCase().indexOf(props.keyChar.toLowerCase()))
    : -1;
  const highlightColor = () => props.highlightColor ?? colors().accent;

  if (idx < 0) {
    return (
      <text>
        <span style={{ fg: colors().textDim }}>{props.label}</span>
        <span style={{ fg: colors().textMuted }}>:</span>
        <span style={{ fg: colors().text }}> {props.value}</span>
      </text>
    );
  }

  const before = props.label.slice(0, idx);
  const key = props.label[idx] ?? props.keyChar ?? "";
  const after = props.label.slice(idx + 1);

  return (
    <text>
      <span style={{ fg: colors().textDim }}>{before}</span>
      <span style={{ fg: highlightColor(), bold: true }}>{key}</span>
      <span style={{ fg: colors().textDim }}>{after}</span>
      <span style={{ fg: colors().textMuted }}>:</span>
      <span style={{ fg: colors().text }}> {props.value}</span>
    </text>
  );
}

function truncateLabel(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  if (maxLength <= 3) return value.slice(0, Math.max(0, maxLength));
  return `${value.slice(0, maxLength - 3)}...`;
}

export function Footer(): JSX.Element {
  const { colors } = useTheme();
  const config = useConfig();
  const transcriber = useTranscriber();
  const terminal = useTerminalDimensions();

  const modelName = () => config.config()?.model.name ?? "-";
  const hotkeyMode = () => config.config()?.hotkey.mode ?? "-";
  const hotkeyKey = () => config.config()?.hotkey.key ?? "-";

  const compactModel = () => truncateLabel(modelName(), 14);
  const compactHotkey = () => truncateLabel(hotkeyKey(), 14);

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

  const statusMaxChars = () => {
    const leftSectionWidth = Math.floor(terminal().width * 0.33);
    const scannerSectionWidth = 8;
    const statusGap = 2;
    return Math.max(8, leftSectionWidth - scannerSectionWidth - statusGap - 2);
  };

  const statusDisplay = () => {
    const oneLine = transcriber.statusMessage().replace(/\s+/g, " ").trim();
    return truncateLabel(oneLine || "-", statusMaxChars());
  };

  return (
    <box
      paddingX={2}
      paddingTop={1}
      paddingBottom={1}
      backgroundColor={colors().backgroundPanel}
      flexShrink={0}
    >
      <box flexDirection="row" alignItems="center" width="100%">
        <box width="33%" flexDirection="row" alignItems="center" gap={2} flexShrink={1}>
          <box width={8} justifyContent="flex-start" alignItems="flex-start" flexShrink={0}>
            <Scanner active={transcriber.isBusy()} />
          </box>
          <text flexShrink={1}>
            <span style={{ fg: statusColor() }}>{statusDisplay()}</span>
          </text>
        </box>

        <box width="34%" justifyContent="center" flexDirection="row" gap={3} alignItems="center" flexShrink={0}>
          <PairHint label="model" keyChar="m" value={compactModel()} highlightColor={colors().secondary} />
          <PairHint label="hotkey" keyChar="h" value={compactHotkey()} highlightColor={colors().secondary} />
          <PairHint label="mode" keyChar="o" value={hotkeyMode()} highlightColor={colors().secondary} />
        </box>

        <box width="33%" justifyContent="flex-end" flexDirection="row" gap={2} alignItems="center" flexShrink={0}>
          <KeyHint keyChar="q" word="quit" />
          <KeyHint keyChar="l" word="logs" />
          <KeyHint keyChar="s" word="settings" />
        </box>
      </box>
    </box>
  );
}
