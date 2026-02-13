import { createSignal, createEffect, onCleanup, type Accessor, type JSX } from "solid-js";
import { useTheme } from "../context/theme";

// Braille spinner frames (like opencode)
const BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_INTERVAL = 80;

function createScannerFrames(width = 9, holdFrames = 2): string[] {
  const inactive = "⬝";
  const active = "■";
  const frames: string[] = [];

  const renderFrame = (activeIndex: number) => {
    return Array.from({ length: width }, (_, i) => (i === activeIndex ? active : inactive)).join("");
  };

  for (let i = 0; i < width; i++) {
    frames.push(renderFrame(i));
  }

  for (let i = 0; i < holdFrames; i++) {
    frames.push(renderFrame(width - 1));
  }

  for (let i = width - 2; i >= 0; i--) {
    frames.push(renderFrame(i));
  }

  for (let i = 0; i < holdFrames; i++) {
    frames.push(renderFrame(0));
  }

  return frames;
}

const SCANNER_FRAMES = createScannerFrames();
const SCANNER_INTERVAL = 45;

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

export function useScannerFrame(): Accessor<string> {
  return useSpinnerFrame(SCANNER_FRAMES, SCANNER_INTERVAL);
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
