import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useConfig } from "../context/config";

interface ToggleHintProps {
  keyChar: string;
  label: string;
  active: boolean;
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

export function Header(): JSX.Element {
  const { colors } = useTheme();
  const config = useConfig();

  return (
    <box
      paddingX={2}
      paddingTop={1}
      paddingBottom={0}
    >
      <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
        <text>
          <span style={{ fg: colors().primary }}>whisper.local</span>
        </text>

        <box
          justifyContent="flex-end"
          flexDirection="row"
          gap={2}
          alignItems="center"
          flexShrink={0}
        >
          <ToggleHint keyChar="n" label="noise" active={config.noiseEnabled()} />
          <ToggleHint keyChar="v" label="vad" active={config.vadEnabled()} />
          <ToggleHint keyChar="a" label="auto-copy" active={config.autoCopy()} />
        </box>
      </box>
    </box>
  );
}
