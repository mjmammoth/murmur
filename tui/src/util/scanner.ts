import type { ColorInput } from "@opentui/core";
import { RGBA } from "@opentui/core";
import type { ColorGenerator } from "opentui-spinner";

interface TrailOptions {
  colors: RGBA[];
  trailLength: number;
  defaultColor: RGBA;
  holdFrames: { start: number; end: number };
  minAlpha: number;
}

interface ScannerState {
  activePosition: number;
  isHolding: boolean;
  holdProgress: number;
  holdTotal: number;
  movementProgress: number;
  movementTotal: number;
  isMovingForward: boolean;
}

function getScannerState(frameIndex: number, width: number, holdFrames: { start: number; end: number }): ScannerState {
  const forwardFrames = width;
  const holdEndFrames = holdFrames.end;
  const backwardFrames = width - 1;

  if (frameIndex < forwardFrames) {
    return {
      activePosition: frameIndex,
      isHolding: false,
      holdProgress: 0,
      holdTotal: 0,
      movementProgress: frameIndex,
      movementTotal: forwardFrames,
      isMovingForward: true,
    };
  }

  if (frameIndex < forwardFrames + holdEndFrames) {
    return {
      activePosition: width - 1,
      isHolding: true,
      holdProgress: frameIndex - forwardFrames,
      holdTotal: holdEndFrames,
      movementProgress: 0,
      movementTotal: 0,
      isMovingForward: true,
    };
  }

  if (frameIndex < forwardFrames + holdEndFrames + backwardFrames) {
    const backwardIndex = frameIndex - forwardFrames - holdEndFrames;
    return {
      activePosition: width - 2 - backwardIndex,
      isHolding: false,
      holdProgress: 0,
      holdTotal: 0,
      movementProgress: backwardIndex,
      movementTotal: backwardFrames,
      isMovingForward: false,
    };
  }

  return {
    activePosition: 0,
    isHolding: true,
    holdProgress: frameIndex - forwardFrames - holdEndFrames - backwardFrames,
    holdTotal: holdFrames.start,
    movementProgress: 0,
    movementTotal: 0,
    isMovingForward: false,
  };
}

function calculateColorIndex(frameIndex: number, charIndex: number, width: number, options: TrailOptions): number {
  const state = getScannerState(frameIndex, width, options.holdFrames);
  const { activePosition, isHolding, holdProgress, isMovingForward } = state;

  const directionalDistance = isMovingForward
    ? activePosition - charIndex
    : charIndex - activePosition;

  if (isHolding) {
    return directionalDistance + holdProgress;
  }

  if (directionalDistance > 0 && directionalDistance < options.trailLength) {
    return directionalDistance;
  }

  if (directionalDistance === 0) {
    return 0;
  }

  return -1;
}

function createKnightRiderTrail(options: TrailOptions): ColorGenerator {
  const defaultRgba = RGBA.fromValues(
    options.defaultColor.r,
    options.defaultColor.g,
    options.defaultColor.b,
    options.defaultColor.a
  );
  const baseInactiveAlpha = defaultRgba.a;

  let cachedFrameIndex = -1;
  let cachedState: ScannerState | null = null;

  return (frameIndex: number, charIndex: number, _totalFrames: number, totalChars: number) => {
    if (frameIndex !== cachedFrameIndex) {
      cachedFrameIndex = frameIndex;
      cachedState = getScannerState(frameIndex, totalChars, options.holdFrames);
    }

    const state = cachedState;
    if (!state) return defaultRgba;

    const index = calculateColorIndex(frameIndex, charIndex, totalChars, options);

    let fadeFactor = 1;
    if (state.isHolding && state.holdTotal > 0) {
      const progress = Math.min(state.holdProgress / state.holdTotal, 1);
      fadeFactor = Math.max(options.minAlpha, 1 - progress * (1 - options.minAlpha));
    } else if (!state.isHolding && state.movementTotal > 0) {
      const progress = Math.min(state.movementProgress / Math.max(1, state.movementTotal - 1), 1);
      fadeFactor = options.minAlpha + progress * (1 - options.minAlpha);
    }

    defaultRgba.a = baseInactiveAlpha * fadeFactor;

    if (index === -1) {
      return defaultRgba;
    }

    return options.colors[index] ?? defaultRgba;
  };
}

function deriveTrailColors(brightColor: ColorInput, steps: number): RGBA[] {
  const base = brightColor instanceof RGBA ? brightColor : RGBA.fromHex(brightColor as string);
  const colors: RGBA[] = [];

  for (let i = 0; i < steps; i++) {
    let alpha: number;
    let brightnessFactor: number;

    if (i === 0) {
      alpha = 1;
      brightnessFactor = 1;
    } else if (i === 1) {
      alpha = 0.9;
      brightnessFactor = 1.15;
    } else {
      alpha = Math.pow(0.65, i - 1);
      brightnessFactor = 1;
    }

    const r = Math.min(1, base.r * brightnessFactor);
    const g = Math.min(1, base.g * brightnessFactor);
    const b = Math.min(1, base.b * brightnessFactor);
    colors.push(RGBA.fromValues(r, g, b, alpha));
  }

  return colors;
}

function deriveInactiveColor(brightColor: ColorInput, factor: number): RGBA {
  const base = brightColor instanceof RGBA ? brightColor : RGBA.fromHex(brightColor as string);
  return RGBA.fromValues(base.r, base.g, base.b, factor);
}

export interface ScannerOptions {
  width?: number;
  holdStart?: number;
  holdEnd?: number;
  color: ColorInput;
  trailSteps?: number;
  inactiveFactor?: number;
  minAlpha?: number;
}

function buildTrailOptions(options: ScannerOptions): TrailOptions {
  const holdStart = options.holdStart ?? 30;
  const holdEnd = options.holdEnd ?? 9;
  const trailSteps = options.trailSteps ?? 6;
  const inactiveFactor = options.inactiveFactor ?? 0.6;
  const minAlpha = options.minAlpha ?? 0.3;

  const colors = deriveTrailColors(options.color, trailSteps);
  const defaultColor = deriveInactiveColor(options.color, inactiveFactor);

  return {
    colors,
    trailLength: colors.length,
    defaultColor,
    holdFrames: { start: holdStart, end: holdEnd },
    minAlpha,
  };
}

export function createFrames(options: ScannerOptions): string[] {
  const width = options.width ?? 8;
  const holdStart = options.holdStart ?? 30;
  const holdEnd = options.holdEnd ?? 9;
  const trailOptions = buildTrailOptions(options);

  const totalFrames = width + holdEnd + (width - 1) + holdStart;

  return Array.from({ length: totalFrames }, (_, frameIndex) => {
    return Array.from({ length: width }, (_, charIndex) => {
      const index = calculateColorIndex(frameIndex, charIndex, width, trailOptions);
      const isActive = index >= 0 && index < trailOptions.colors.length;
      return isActive ? "■" : "⬝";
    }).join("");
  });
}

export function createColors(options: ScannerOptions): ColorGenerator {
  return createKnightRiderTrail(buildTrailOptions(options));
}
