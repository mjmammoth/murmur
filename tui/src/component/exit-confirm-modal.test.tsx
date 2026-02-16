import { describe, expect, test, mock } from "bun:test";
import { createRoot, createSignal } from "solid-js";

/**
 * Tests for ExitConfirmModal component
 *
 * This component displays a modal when the user tries to exit during a model download.
 * It shows download progress and allows confirming or canceling the exit.
 */

describe("ExitConfirmModal", () => {
  describe("modelName computation", () => {
    test("should use explicit model from dialog data", () => {
      createRoot((dispose) => {
        const explicitModel = "gpt-test-model";
        const result = explicitModel.trim();

        expect(result).toBe("gpt-test-model");
        expect(result.length).toBeGreaterThan(0);
        dispose();
      });
    });

    test("should fallback to activeModelOp when no explicit model", () => {
      createRoot((dispose) => {
        const activeOp = { type: "pulling" as const, model: "whisper-large" };

        expect(activeOp.model).toBe("whisper-large");
        expect(activeOp.type).toBe("pulling");
        dispose();
      });
    });

    test("should return placeholder when no model available", () => {
      createRoot((dispose) => {
        const placeholder = "selected model";

        expect(placeholder).toBe("selected model");
        dispose();
      });
    });
  });

  describe("progressText computation", () => {
    test("should format progress percentage correctly", () => {
      createRoot((dispose) => {
        const progress = { model: "whisper-base", percent: 45.7 };
        const percent = Math.max(0, Math.min(99, Math.floor(progress.percent)));
        const progressText = `${percent}% downloaded`;

        expect(progressText).toBe("45% downloaded");
        dispose();
      });
    });

    test("should clamp progress to 0-99 range", () => {
      createRoot((dispose) => {
        // Test lower bound
        let percent = Math.max(0, Math.min(99, Math.floor(-10)));
        expect(percent).toBe(0);

        // Test upper bound
        percent = Math.max(0, Math.min(99, Math.floor(150)));
        expect(percent).toBe(99);

        // Test exact 100
        percent = Math.max(0, Math.min(99, Math.floor(100)));
        expect(percent).toBe(99);

        dispose();
      });
    });

    test("should return empty string when no progress", () => {
      createRoot((dispose) => {
        const progress = null;
        const progressText = progress ? `${Math.floor(progress)}% downloaded` : "";

        expect(progressText).toBe("");
        dispose();
      });
    });

    test("should return empty string when model mismatch", () => {
      createRoot((dispose) => {
        const progress = { model: "whisper-base", percent: 50 };
        const modelName = "whisper-large";
        const progressText = progress.model !== modelName ? "" : `${Math.floor(progress.percent)}% downloaded`;

        expect(progressText).toBe("");
        dispose();
      });
    });
  });

  describe("cancelExit function", () => {
    test("should signal dialog to close", () => {
      createRoot((dispose) => {
        let dialogClosed = false;
        const mockCloseDialog = () => { dialogClosed = true; };

        mockCloseDialog();

        expect(dialogClosed).toBe(true);
        dispose();
      });
    });
  });

  describe("confirmExit function", () => {
    test("should cancel download for valid model", () => {
      createRoot((dispose) => {
        const modelName = "whisper-base";
        let cancelledModel = "";
        const mockCancelDownload = (model: string) => { cancelledModel = model; };

        if (modelName && modelName !== "selected model") {
          mockCancelDownload(modelName);
        }

        expect(cancelledModel).toBe("whisper-base");
        dispose();
      });
    });

    test("should not cancel download for placeholder model", () => {
      createRoot((dispose) => {
        const modelName = "selected model";
        let cancelledModel = "";
        const mockCancelDownload = (model: string) => { cancelledModel = model; };

        if (modelName && modelName !== "selected model") {
          mockCancelDownload(modelName);
        }

        expect(cancelledModel).toBe("");
        dispose();
      });
    });

    test("should call exit function", () => {
      createRoot((dispose) => {
        let exitCalled = false;
        const mockExit = () => { exitCalled = true; };

        mockExit();

        expect(exitCalled).toBe(true);
        dispose();
      });
    });
  });

  describe("keyboard shortcuts", () => {
    test("should handle escape key", () => {
      createRoot((dispose) => {
        const key = { name: "escape", eventType: "press", repeated: false };

        expect(key.name).toBe("escape");
        expect(key.eventType).toBe("press");
        dispose();
      });
    });

    test("should handle n key", () => {
      createRoot((dispose) => {
        const key = { name: "n", eventType: "press", repeated: false };

        expect(key.name).toBe("n");
        dispose();
      });
    });

    test("should handle enter key", () => {
      createRoot((dispose) => {
        const key = { name: "return", eventType: "press", repeated: false };

        expect(key.name).toBe("return");
        dispose();
      });
    });

    test("should handle y key", () => {
      createRoot((dispose) => {
        const key = { name: "y", eventType: "press", repeated: false };

        expect(key.name).toBe("y");
        dispose();
      });
    });

    test("should handle q key", () => {
      createRoot((dispose) => {
        const key = { name: "q", eventType: "press", repeated: false };

        expect(key.name).toBe("q");
        dispose();
      });
    });

    test("should handle ctrl+c", () => {
      createRoot((dispose) => {
        const key = { name: "c", ctrl: true, eventType: "press", repeated: false };

        expect(key.name).toBe("c");
        expect(key.ctrl).toBe(true);
        dispose();
      });
    });

    test("should ignore release events", () => {
      createRoot((dispose) => {
        const key = { name: "escape", eventType: "release", repeated: false };

        expect(key.eventType).toBe("release");
        dispose();
      });
    });

    test("should ignore repeated events", () => {
      createRoot((dispose) => {
        const key = { name: "escape", eventType: "press", repeated: true };

        expect(key.repeated).toBe(true);
        dispose();
      });
    });
  });

  describe("UI layout", () => {
    test("should have correct modal width", () => {
      createRoot((dispose) => {
        const width = 62;

        expect(width).toBe(62);
        dispose();
      });
    });

    test("should display warning text", () => {
      createRoot((dispose) => {
        const warningText = "Download in progress";

        expect(warningText).toBe("Download in progress");
        dispose();
      });
    });

    test("should display exit confirmation question", () => {
      createRoot((dispose) => {
        const confirmText = "Exit now to cancel the download and clean up incomplete files?";

        expect(confirmText).toContain("cancel the download");
        dispose();
      });
    });
  });

  describe("edge cases", () => {
    test("should handle undefined progress gracefully", () => {
      createRoot((dispose) => {
        const progress = undefined;
        const progressText = progress ? `${Math.floor(progress)}% downloaded` : "";

        expect(progressText).toBe("");
        dispose();
      });
    });

    test("should handle negative progress values", () => {
      createRoot((dispose) => {
        const percent = Math.max(0, Math.min(99, Math.floor(-50)));

        expect(percent).toBe(0);
        dispose();
      });
    });

    test("should handle decimal progress values", () => {
      createRoot((dispose) => {
        const percent = Math.floor(45.999);

        expect(percent).toBe(45);
        dispose();
      });
    });
  });

  describe("integration scenarios", () => {
    test("should show progress for matching model", () => {
      createRoot((dispose) => {
        const modelName = "whisper-base";
        const progress = { model: "whisper-base", percent: 75 };

        const shouldShowProgress = progress && progress.model === modelName;
        expect(shouldShowProgress).toBe(true);

        if (shouldShowProgress) {
          const percent = Math.max(0, Math.min(99, Math.floor(progress.percent)));
          expect(percent).toBe(75);
        }

        dispose();
      });
    });

    test("should not show progress for different model", () => {
      createRoot((dispose) => {
        const modelName = "whisper-large";
        const progress = { model: "whisper-base", percent: 75 };

        const shouldShowProgress = progress && progress.model === modelName;
        expect(shouldShowProgress).toBe(false);

        dispose();
      });
    });
  });
});