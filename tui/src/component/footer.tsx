import { Show, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useConfig } from "../context/config";
import { useBackend } from "../context/backend";

interface KeyHintProps {
  keys: string;
  label: string;
}

function KeyHint(props: KeyHintProps): JSX.Element {
  const { colors } = useTheme();

  return (
    <text>
      <span style={{ fg: colors().text }}>{props.keys}</span>
      <span style={{ fg: colors().textMuted }}> {props.label}</span>
    </text>
  );
}

interface ToggleHintProps {
  label: string;
  active: boolean;
}

function ToggleHint(props: ToggleHintProps): JSX.Element {
  const { colors } = useTheme();

  return (
    <text>
      <span style={{ fg: colors().textDim }}>{props.label}</span>
      <span style={{ fg: colors().textMuted }}>:</span>
      <span style={{ fg: props.active ? colors().success : colors().textDim }}>
        {props.active ? " on" : " off"}
      </span>
    </text>
  );
}

export function Footer(): JSX.Element {
  const { colors } = useTheme();
  const config = useConfig();
  const backend = useBackend();

  return (
    <box
      paddingX={2}
      paddingTop={1}
      paddingBottom={2}
      backgroundColor={colors().backgroundPanel}
    >
      <box flexDirection="row" justifyContent="space-between" width="100%">
        <box flexDirection="row" gap={3} alignItems="center">
          <KeyHint keys="q" label="quit" />
          <KeyHint keys="c" label="copy" />
          <KeyHint keys="↵" label="select" />
          <KeyHint keys="m" label="models" />
          <KeyHint keys="l" label="logs" />
          <KeyHint keys="s" label="settings" />
        </box>

        <box flexDirection="row" gap={2} alignItems="center">
          <ToggleHint label="noise" active={config.noiseEnabled()} />
          <ToggleHint label="vad" active={config.vadEnabled()} />
          <ToggleHint label="auto" active={config.autoCopy()} />

          <Show when={!backend.connected()}>
            <text>
              <span style={{ fg: colors().warning }}>offline</span>
              <span style={{ fg: colors().textMuted }}> bridge</span>
            </text>
          </Show>
        </box>
      </box>
    </box>
  );
}
