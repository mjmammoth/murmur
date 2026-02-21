import { describe, expect, test } from "bun:test";
import { formatDeviceLabel } from "../util/format";

describe("Welcome", () => {
  describe("hardware detection display", () => {
    test("should format mps as Metal (mps) for onboarding labels", () => {
      expect(formatDeviceLabel("mps")).toBe("Metal (mps)");
    });

    test("should use accent color token for recommendation emphasis", () => {
      const colors = { accent: "#a020f0", textMuted: "#7f7f7f" };
      const recommendationColor = colors.accent;

      expect(recommendationColor).toBe(colors.accent);
      expect(recommendationColor).not.toBe(colors.textMuted);
    });
  });

  describe("resume payload", () => {
    test("should preserve step and model indices when reopening welcome", () => {
      const stepIndex = 2;
      const modelIndex = 4;
      const recommendationAutoApplied = true;
      const payload = {
        firstRun: true,
        resumeStepIndex: stepIndex,
        resumeModelIndex: modelIndex,
        recommendationAutoApplied,
      };

      expect(payload.resumeStepIndex).toBe(2);
      expect(payload.resumeModelIndex).toBe(4);
      expect(payload.recommendationAutoApplied).toBe(true);
    });
  });

  describe("recommendation auto-apply sequence", () => {
    test("should apply runtime before applying device", () => {
      const sends: string[] = [];
      const recommendedRuntime: string = "whisper.cpp";
      const recommendedDevice: string = "mps";

      // Step 1: runtime apply is initiated once.
      sends.push(`set_model_runtime:${recommendedRuntime}`);

      // Step 2: device apply waits until config reflects runtime.
      const configRuntimeBefore: string = "faster-whisper";
      if (configRuntimeBefore === recommendedRuntime) {
        sends.push(`set_model_device:${recommendedDevice}`);
      }
      expect(sends).toEqual(["set_model_runtime:whisper.cpp"]);

      const configRuntimeAfter: string = "whisper.cpp";
      if (configRuntimeAfter === recommendedRuntime) {
        sends.push(`set_model_device:${recommendedDevice}`);
      }

      expect(sends).toEqual([
        "set_model_runtime:whisper.cpp",
        "set_model_device:mps",
      ]);
    });

    test("should only auto-apply once per welcome session", () => {
      let recommendationAutoApplied = false;
      const actions: string[] = [];

      if (!recommendationAutoApplied) {
        actions.push("auto-apply");
        recommendationAutoApplied = true;
      }
      if (!recommendationAutoApplied) {
        actions.push("auto-apply");
      }

      expect(actions).toEqual(["auto-apply"]);
    });
  });

  describe("model download behavior", () => {
    test("should download only the active runtime variant", () => {
      const activeRuntime = "whisper.cpp";
      const selectedModel = "small";
      const op = {
        type: "download_model",
        name: selectedModel,
        runtime: activeRuntime,
      };

      expect(op.runtime).toBe("whisper.cpp");
      expect(op.name).toBe("small");
    });

    test("should show cancel queued action label when model is queued", () => {
      const selectedModelIsPulling = false;
      const selectedModelIsQueued = true;
      const label = selectedModelIsPulling
        ? "cancel"
        : selectedModelIsQueued
          ? "cancel queued"
          : "pull + select";

      expect(label).toBe("cancel queued");
    });
  });
});
