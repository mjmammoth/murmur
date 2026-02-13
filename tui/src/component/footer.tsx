import { Show, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useConfig } from "../context/config";
import { useBackend } from "../context/backend";
import { useTranscriber } from "../context/transcriber";
import { useScannerFrame } from "./spinner";

interface KeyHintProps {
  keyChar: string;
  word: string;
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

interface ToggleHintProps {
  keyChar: string;
  label: string;
  active: boolean;
}

interface PairHintProps {
  label: string;
  value: string;
  keyChar?: string;
}

function ToggleHint(props: ToggleHintProps): JSX.Element {
  const { colors } = useTheme();
  const idx = Math.max(0, props.label.toLowerCase().indexOf(props.keyChar.toLowerCase()));
  const before = props.label.slice(0, idx);
  const key = props.label[idx] ?? props.keyChar;
  const after = props.label.slice(idx + 1);

  return (
    <text>
      <span style={{ fg: colors().textDim }}>{before}</span>
      <span style={{ fg: colors().accent, bold: true }}>{key}</span>
      <span style={{ fg: colors().textDim }}>{after}</span>
      <span style={{ fg: colors().textMuted }}>:</span>
      <span style={{ fg: props.active ? colors().success : colors().textDim }}>
        {props.active ? " on" : " off"}
      </span>
    </text>
  );
}

function PairHint(props: PairHintProps): JSX.Element {
  const { colors } = useTheme();
  const idx = props.keyChar
    ? Math.max(0, props.label.toLowerCase().indexOf(props.keyChar.toLowerCase()))
    : -1;
  const before = idx >= 0 ? props.label.slice(0, idx) : props.label;
  const key = idx >= 0 ? (props.label[idx] ?? props.keyChar ?? "") : "";
  const after = idx >= 0 ? props.label.slice(idx + 1) : "";

  return (
    <text>
      <span style={{ fg: colors().textDim }}>{before}</span>
      <Show when={idx >= 0}>
        <span style={{ fg: colors().accent, bold: true }}>{key}</span>
      </Show>
      <span style={{ fg: colors().textDim }}>{after}</span>
      <span style={{ fg: colors().textMuted }}>:</span>
      <span style={{ fg: colors().text }}> {props.value}</span>
    </text>
  );
}

export function Footer(): JSX.Element {
  const { colors } = useTheme();
  const config = useConfig();
  const backend = useBackend();
  const transcriber = useTranscriber();
  const scannerFrame = useScannerFrame();

  const modelName = () => config.config()?.model.name ?? "-";

  const hotkeyMode = () => {
    const mode = config.config()?.hotkey.mode;
    if (mode === "ptt") return "push-to-talk";
    if (mode === "toggle") return "toggle";
    return "-";
  };

  const hotkeyKey = () => config.config()?.hotkey.key ?? "-";

  return (
    <box
      paddingX={2}
      paddingTop={1}
      paddingBottom={2}
      backgroundColor={colors().backgroundPanel}
    >
      <box flexDirection="row" justifyContent="space-between" width="100%">
        <box flexDirection="row" gap={3} alignItems="center">
          <KeyHint keyChar="q" word="Quit" />
          <KeyHint keyChar="c" word="Copy" />
          <KeyHint keyChar="h" word="Hotkey" />
          <KeyHint keyChar="l" word="Logs" />
          <KeyHint keyChar="s" word="Settings" />
        </box>

        <box flexDirection="column" alignItems="flex-end" gap={1}>
          <box flexDirection="row" gap={2} alignItems="center">
            <PairHint label="model" keyChar="m" value={modelName()} />
            <PairHint label="hotkey" keyChar="h" value={hotkeyKey()} />
            <PairHint label="mode" value={hotkeyMode()} />
          </box>

          <box flexDirection="row" gap={2} alignItems="center">
            <box flexDirection="row" gap={2} alignItems="center">
              <ToggleHint keyChar="n" label="noise" active={config.noiseEnabled()} />
              <ToggleHint keyChar="v" label="vad" active={config.vadEnabled()} />
              <ToggleHint keyChar="a" label="auto" active={config.autoCopy()} />

              <Show when={!backend.connected()}>
                <text>
                  <span style={{ fg: colors().warning }}>offline</span>
                  <span style={{ fg: colors().textMuted }}> bridge</span>
                </text>
              </Show>
            </box>

            <box width={20} justifyContent="flex-end" alignItems="flex-end">
              <Show
                when={transcriber.isBusy()}
                fallback={<text><span style={{ fg: colors().textDim }}>                    </span></text>}
              >
                <text>
                  <span style={{ fg: colors().secondary }}>{scannerFrame()}</span>
                  <span style={{ fg: colors().textMuted }}> processing</span>
                </text>
              </Show>
            </box>
          </box>
        </box>
      </box>
    </box>
  );
}
