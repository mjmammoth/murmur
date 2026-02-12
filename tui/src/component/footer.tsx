import { Show, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { useConfig } from "../context/config";
import { useBackend } from "../context/backend";

interface KeyHintProps {
  keys: string;
  label: string;
  active?: boolean;
}

function KeyHint(props: KeyHintProps): JSX.Element {
  const { colors } = useTheme();

  return (
    <text>
      <span fg={props.active ? colors().accent : colors().textDim}>[</span>
      <span fg={props.active ? colors().primary : colors().text}>{props.keys}</span>
      <span fg={props.active ? colors().accent : colors().textDim}>]</span>
      <span fg={colors().textMuted}> {props.label} </span>
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
      paddingY={1}
      backgroundColor={colors().backgroundPanel}
      borderStyle="single"
      border={["top"]}
      borderColor={colors().border}
    >
      <box flexDirection="row" justifyContent="space-between" width="100%">
        {/* Left side - Main actions */}
        <box flexDirection="row">
          <KeyHint keys="q" label="quit" />
          <KeyHint keys="c" label="copy" />
          <KeyHint keys="↵" label="copy sel" />
          <KeyHint keys="m" label="models" />
          <KeyHint keys="l" label="logs" />
          <KeyHint keys="s" label="settings" />
        </box>

        {/* Right side - Toggles */}
        <box flexDirection="row">
          <KeyHint keys="y" label="auto" active={config.autoCopy()} />
          <KeyHint keys="n" label="noise" active={config.noiseEnabled()} />
          <KeyHint keys="v" label="vad" active={config.vadEnabled()} />

          <Show when={!backend.connected()}>
            <text fg={colors().warning}> ○ disconnected</text>
          </Show>
        </box>
      </box>
    </box>
  );
}
