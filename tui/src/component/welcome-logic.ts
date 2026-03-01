export type WelcomeStepId = "welcome" | "device-detection" | "model-download" | "help";

export interface WelcomeNextHint {
  keys: string;
  label: string;
  disabled: boolean;
}

export function isModelDownloadStep(step: WelcomeStepId): boolean {
  return step === "model-download";
}

export function shouldAdvanceOnRightKey(step: WelcomeStepId): boolean {
  return !isModelDownloadStep(step);
}

export function resolveNextHint(
  step: WelcomeStepId,
  isLastStep: boolean,
  canClose: boolean,
): WelcomeNextHint {
  if (!isLastStep) {
    return {
      keys: "Right",
      label: "next",
      disabled: !shouldAdvanceOnRightKey(step),
    };
  }
  if (isModelDownloadStep(step)) {
    return {
      keys: "Esc/q",
      label: canClose ? "finish" : "finish (blocked)",
      disabled: !canClose,
    };
  }
  return {
    keys: "Enter",
    label: canClose ? "finish" : "finish (blocked)",
    disabled: !canClose,
  };
}
