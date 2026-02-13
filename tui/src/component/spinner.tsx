import { createSignal, createEffect, onCleanup, type Accessor, type JSX } from "solid-js";
import { useTheme } from "../context/theme";

// Braille spinner frames (like opencode)
const BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_INTERVAL = 80;

/** Reusable hook that returns the current spinner frame character */
export function useSpinnerFrame(
  frames = BRAILLE_FRAMES,
  interval = SPINNER_INTERVAL
): Accessor<string> {
  const [frameIndex, setFrameIndex] = createSignal(0);

  createEffect(() => {
    const timer = setInterval(() => {
      setFrameIndex((idx) => (idx + 1) % frames.length);
    }, interval);

    onCleanup(() => clearInterval(timer));
  });

  return () => frames[frameIndex()];
}

export interface SpinnerProps {
  label?: string;
  color?: string;
}

export function Spinner(props: SpinnerProps): JSX.Element {
  const { colors } = useTheme();
  const frame = useSpinnerFrame();
  const spinnerColor = () => props.color ?? colors().secondary;

  return (
    <box>
      <text>
        <span style={{ fg: spinnerColor() }}>{frame()}</span>
        {props.label && <span style={{ fg: colors().text }}> {props.label}</span>}
      </text>
    </box>
  );
}

// Dots spinner alternative
const DOTS_FRAMES = ["⋯", "⋱", "⋮", "⋰"];

export function DotsSpinner(props: SpinnerProps): JSX.Element {
  const { colors } = useTheme();
  const frame = useSpinnerFrame(DOTS_FRAMES, 200);

  return (
    <box>
      <text>
        <span style={{ fg: props.color ?? colors().textMuted }}>{frame()}</span>
        {props.label && <span style={{ fg: colors().text }}> {props.label}</span>}
      </text>
    </box>
  );
}
