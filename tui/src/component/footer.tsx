import { type JSX } from "solid-js";
import { useTerminalDimensions } from "@opentui/solid";
import { useTheme } from "../context/theme";
import { useConfig } from "../context/config";
import { useTranscriber } from "../context/transcriber";
import { useBackend } from "../context/backend";
import { Scanner } from "./spinner";

interface KeyHintProps {
  keyChar: string;
  word: string;
  onClick?: () => void;
}

interface PairHintProps {
  label: string;
  value: string;
  keyChar?: string;
  highlightColor?: string;
  onClick?: () => void;
}

interface FooterProps {
  availableWidth?: number;
  onStatusClick?: () => void;
  onModelClick?: () => void;
  onHotkeyClick?: () => void;
  onModeClick?: () => void;
  onQuitClick?: () => void;
  onLogsClick?: () => void;
  onSettingsClick?: () => void;
  onThemeClick?: () => void;
}

function KeyHint(props: KeyHintProps): JSX.Element {
  const { colors } = useTheme();
  const idx = Math.max(0, props.word.toLowerCase().indexOf(props.keyChar.toLowerCase()));
  const before = props.word.slice(0, idx);
  const key = props.word[idx] ?? props.keyChar;
  const after = props.word.slice(idx + 1);

  return (
    <box onMouseUp={() => props.onClick?.()}>
      <text>
        <span style={{ fg: colors().textMuted }}>{before}</span>
        <span style={{ fg: colors().accent, bold: true }}>{key}</span>
        <span style={{ fg: colors().textMuted }}>{after}</span>
      </text>
    </box>
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
      <box onMouseUp={() => props.onClick?.()}>
        <text wrapMode="none" truncate>
          <span style={{ fg: colors().textDim }}>{props.label}</span>
          <span style={{ fg: colors().textMuted }}>:</span>
          <span style={{ fg: colors().text }}> {props.value}</span>
        </text>
      </box>
    );
  }

  const before = props.label.slice(0, idx);
  const key = props.label[idx] ?? props.keyChar ?? "";
  const after = props.label.slice(idx + 1);

  return (
    <box onMouseUp={() => props.onClick?.()}>
      <text wrapMode="none" truncate>
        <span style={{ fg: colors().textDim }}>{before}</span>
        <span style={{ fg: highlightColor(), bold: true }}>{key}</span>
        <span style={{ fg: colors().textDim }}>{after}</span>
        <span style={{ fg: colors().textMuted }}>:</span>
        <span style={{ fg: colors().text }}> {props.value}</span>
      </text>
    </box>
  );
}

function truncateLabel(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  if (maxLength <= 3) return value.slice(0, Math.max(0, maxLength));
  return `${value.slice(0, maxLength - 3)}...`;
}

export function Footer(props: FooterProps): JSX.Element {
  const COMPACT_FOOTER_THRESHOLD = 118;
  const { colors } = useTheme();
  const config = useConfig();
  const backend = useBackend();
  const transcriber = useTranscriber();
  const terminal = useTerminalDimensions();
  const availableWidth = () => Math.max(0, Math.floor(props.availableWidth ?? terminal().width));

  const modelName = () => {
    const selected = config.config()?.model.name;
    if (!selected) return "-";
    const match = backend.models().find((model) => model.name === selected);
    return match?.installed ? selected : "-";
  };
  const hotkeyMode = () => config.config()?.hotkey.mode ?? "-";
  const hotkeyKey = () => config.config()?.hotkey.key ?? "-";
  const compactFooterLayout = () => availableWidth() < COMPACT_FOOTER_THRESHOLD;

  const compactModel = () => truncateLabel(modelName(), compactFooterLayout() ? 10 : 14);
  const compactHotkey = () => truncateLabel(hotkeyKey(), compactFooterLayout() ? 10 : 14);
  const leftSectionWidth = () => Math.floor(availableWidth() * 0.33);
  const shouldWrapLeftSection = () => compactFooterLayout();
  const shouldWrapRightSection = () => compactFooterLayout();

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
    const sectionWidth = leftSectionWidth();
    if (shouldWrapLeftSection()) {
      return Math.max(8, sectionWidth - 2);
    }
    const scannerSectionWidth = 8;
    const statusGap = 2;
    return Math.max(8, sectionWidth - scannerSectionWidth - statusGap - 2);
  };

  const statusDisplay = () => {
    const oneLine = transcriber.statusMessage().replace(/\s+/g, " ").trim();
    return truncateLabel(oneLine || "-", statusMaxChars());
  };

  const statusBadgeBackground = () => {
    const status = transcriber.status();
    if (status === "ready") return colors().ready;
    if (status === "recording") return colors().recording;
    if (status === "transcribing" || status === "downloading") return colors().transcribing;
    return null;
  };

  return (
    <box
      paddingX={2}
      paddingTop={1}
      paddingBottom={1}
      backgroundColor={colors().backgroundPanel}
      flexShrink={0}
    >
      <box flexDirection="row" alignItems={compactFooterLayout() ? "flex-start" : "center"} width="100%">
        <box
          width="33%"
          flexDirection={shouldWrapLeftSection() ? "column" : "row"}
          alignItems={shouldWrapLeftSection() ? "flex-start" : "center"}
          gap={shouldWrapLeftSection() ? 0 : 2}
          flexShrink={1}
          onMouseUp={props.onStatusClick}
        >
          <box width={8} justifyContent="flex-start" alignItems="flex-start" flexShrink={0}>
            <Scanner active={transcriber.isBusy()} />
          </box>
          {statusBadgeBackground() ? (
            <box backgroundColor={statusBadgeBackground() ?? undefined} paddingX={1} flexShrink={1}>
              <text flexShrink={1}>
                <span style={{ fg: colors().selectedText, bold: true }}>{statusDisplay()}</span>
              </text>
            </box>
          ) : (
            <text flexShrink={1}>
              <span style={{ fg: statusColor() }}>{statusDisplay()}</span>
            </text>
          )}
        </box>

        <box
          width="34%"
          justifyContent="center"
          flexDirection={compactFooterLayout() ? "column" : "row"}
          gap={compactFooterLayout() ? 0 : 3}
          alignItems="center"
          flexShrink={0}
        >
          {compactFooterLayout() ? (
            <>
              <box width="100%" flexDirection="row" justifyContent="center" gap={3}>
                <PairHint
                  label="model"
                  keyChar="m"
                  value={compactModel()}
                  highlightColor={colors().secondary}
                  onClick={props.onModelClick}
                />
                <PairHint
                  label="hotkey"
                  keyChar="h"
                  value={compactHotkey()}
                  highlightColor={colors().secondary}
                  onClick={props.onHotkeyClick}
                />
              </box>
              <box width="100%" flexDirection="row" justifyContent="center" gap={3}>
                <PairHint
                  label="mode"
                  keyChar="o"
                  value={hotkeyMode()}
                  highlightColor={colors().secondary}
                  onClick={props.onModeClick}
                />
              </box>
            </>
          ) : (
            <>
              <PairHint
                label="model"
                keyChar="m"
                value={compactModel()}
                highlightColor={colors().secondary}
                onClick={props.onModelClick}
              />
              <PairHint
                label="hotkey"
                keyChar="h"
                value={compactHotkey()}
                highlightColor={colors().secondary}
                onClick={props.onHotkeyClick}
              />
              <PairHint
                label="mode"
                keyChar="o"
                value={hotkeyMode()}
                highlightColor={colors().secondary}
                onClick={props.onModeClick}
              />
            </>
          )}
        </box>

        <box
          width="33%"
          justifyContent={shouldWrapRightSection() ? "flex-start" : "flex-end"}
          flexDirection={shouldWrapRightSection() ? "column" : "row"}
          gap={shouldWrapRightSection() ? 0 : 2}
          alignItems="flex-end"
          flexShrink={0}
        >
          {shouldWrapRightSection() ? (
            <>
              <box width="100%" flexDirection="row" justifyContent="flex-end" gap={2}>
                <KeyHint keyChar="q" word="quit" onClick={props.onQuitClick} />
                <KeyHint keyChar="l" word="logs" onClick={props.onLogsClick} />
              </box>
              <box width="100%" flexDirection="row" justifyContent="flex-end" gap={2}>
                <KeyHint keyChar="s" word="settings" onClick={props.onSettingsClick} />
                <KeyHint keyChar="t" word="theme" onClick={props.onThemeClick} />
              </box>
            </>
          ) : (
            <>
              <KeyHint keyChar="q" word="quit" onClick={props.onQuitClick} />
              <KeyHint keyChar="l" word="logs" onClick={props.onLogsClick} />
              <KeyHint keyChar="s" word="settings" onClick={props.onSettingsClick} />
              <KeyHint keyChar="t" word="theme" onClick={props.onThemeClick} />
            </>
          )}
        </box>
      </box>
    </box>
  );
}
