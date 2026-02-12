import { createSignal, createEffect, onCleanup, type JSX } from "solid-js";
import { useTheme } from "../context/theme";

// Braille spinner frames (like opencode)
const BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_INTERVAL = 80;

export interface SpinnerProps {
  label?: string;
  color?: string;
}

export function Spinner(props: SpinnerProps): JSX.Element {
  const { colors } = useTheme();
  const [frameIndex, setFrameIndex] = createSignal(0);

  createEffect(() => {
    const timer = setInterval(() => {
      setFrameIndex((idx) => (idx + 1) % BRAILLE_FRAMES.length);
    }, SPINNER_INTERVAL);

    onCleanup(() => clearInterval(timer));
  });

  const frame = () => BRAILLE_FRAMES[frameIndex()];
  const spinnerColor = () => props.color ?? colors().primary;

  return (
    <box>
      <text>
        <span fg={spinnerColor()}>{frame()}</span>
        {props.label && <span fg={colors().text}> {props.label}</span>}
      </text>
    </box>
  );
}

// Dots spinner alternative
const DOTS_FRAMES = ["⋯", "⋱", "⋮", "⋰"];

export function DotsSpinner(props: SpinnerProps): JSX.Element {
  const { colors } = useTheme();
  const [frameIndex, setFrameIndex] = createSignal(0);

  createEffect(() => {
    const timer = setInterval(() => {
      setFrameIndex((idx) => (idx + 1) % DOTS_FRAMES.length);
    }, 200);

    onCleanup(() => clearInterval(timer));
  });

  const frame = () => DOTS_FRAMES[frameIndex()];

  return (
    <box>
      <text>
        <span fg={props.color ?? colors().textMuted}>{frame()}</span>
        {props.label && <span fg={colors().text}> {props.label}</span>}
      </text>
    </box>
  );
}
