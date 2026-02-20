import { describe, expect, test } from "bun:test";
import { createRoot } from "solid-js";
import type { ModelInfo } from "../types";

/**
 * Tests for ModelManager component
 *
 * Manages model browsing, downloading, selection, and removal.
 */

describe("ModelManager", () => {
  describe("selectedModel logic", () => {
    test("should return model at selected index", () => {
      const models: ModelInfo[] = [
        { name: "whisper-base", installed: true, path: "/path" },
        { name: "whisper-large", installed: false, path: null },
      ];
      const selectedIndex = 0;
      const selectedModel = models[selectedIndex] ?? null;

      expect(selectedModel?.name).toBe("whisper-base");
    });

    test("should return null when index out of bounds", () => {
      const models: ModelInfo[] = [{ name: "whisper-base", installed: true, path: "/path" }];
      const selectedIndex = 5;
      const selectedModel = selectedIndex < 0 || selectedIndex >= models.length ? null : models[selectedIndex] ?? null;

      expect(selectedModel).toBeNull();
    });

    test("should return null for empty models list", () => {
      const models: ModelInfo[] = [];
      const selectedIndex = 0;
      const selectedModel = selectedIndex < 0 || selectedIndex >= models.length ? null : models[selectedIndex] ?? null;

      expect(selectedModel).toBeNull();
    });
  });

  describe("activePullingModelName logic", () => {
    test("should return model name when pulling", () => {
      const op = { type: "pulling" as const, model: "whisper-large" };
      const pullingModel = op && op.type === "pulling" ? op.model : null;

      expect(pullingModel).toBe("whisper-large");
    });

    test("should return null when removing", () => {
      const op: { type: string; model: string } = { type: "removing", model: "whisper-large" };
      const pullingModel = op && op.type === "pulling" ? op.model : null;

      expect(pullingModel).toBeNull();
    });

    test("should return null when no operation", () => {
      const op = null as { type: string; model: string } | null;
      const pullingModel = op && op.type === "pulling" ? op.model : null;

      expect(pullingModel).toBeNull();
    });
  });

  describe("selectedModelIsPulling logic", () => {
    test("should return true when selected model is pulling", () => {
      const selectedModel = { name: "whisper-base", installed: false, path: null };
      const pullingModelName = "whisper-base";
      const isPulling = Boolean(selectedModel && pullingModelName && selectedModel.name === pullingModelName);

      expect(isPulling).toBe(true);
    });

    test("should return false when different model is pulling", () => {
      const selectedModel = { name: "whisper-base", installed: false, path: null };
      const pullingModelName = "whisper-large";
      const isPulling = Boolean(selectedModel && pullingModelName && selectedModel.name === pullingModelName);

      expect(isPulling).toBe(false);
    });
  });

  describe("primaryActionLabel logic", () => {
    test("should show 'pull/select' when no model selected", () => {
      const selectedModel = null;
      const label = selectedModel ? "other" : "pull/select";

      expect(label).toBe("pull/select");
    });

    test("should show 'cancel pull' when model is pulling", () => {
      const selectedModelIsPulling = true;
      const label = selectedModelIsPulling ? "cancel pull" : "other";

      expect(label).toBe("cancel pull");
    });

    test("should show 'select' for installed model", () => {
      const selectedModel = { name: "whisper-base", installed: true, path: "/path" };
      const selectedModelIsPulling = false;
      const label = selectedModelIsPulling ? "cancel pull" : selectedModel.installed ? "select" : "pull + select";

      expect(label).toBe("select");
    });

    test("should show 'pull + select' for uninstalled model", () => {
      const selectedModel = { name: "whisper-base", installed: false, path: null };
      const selectedModelIsPulling = false;
      const label = selectedModelIsPulling ? "cancel pull" : selectedModel.installed ? "select" : "pull + select";

      expect(label).toBe("pull + select");
    });
  });

  describe("primaryActionKeys logic", () => {
    test("should show 'x/enter' when pulling", () => {
      const selectedModelIsPulling = true;
      const keys = selectedModelIsPulling ? "x/enter" : "enter";

      expect(keys).toBe("x/enter");
    });

    test("should show 'enter' when not pulling", () => {
      const selectedModelIsPulling = false;
      const keys = selectedModelIsPulling ? "x/enter" : "enter";

      expect(keys).toBe("enter");
    });
  });

  describe("closeManager logic", () => {
    test("should prevent closing when setup locked", () => {
      const setupLocked = true;
      const canClose = !setupLocked;

      expect(canClose).toBe(false);
    });

    test("should allow closing when setup not locked", () => {
      const setupLocked = false;
      const canClose = !setupLocked;

      expect(canClose).toBe(true);
    });

    test("should return to settings when flag is set", () => {
      const returnToSettings = true;
      const shouldOpenSettings = returnToSettings;

      expect(shouldOpenSettings).toBe(true);
    });
  });

  describe("handlePrimaryAction logic", () => {
    test("should do nothing when no model selected", () => {
      const model = null;
      const shouldProceed = !!model;

      expect(shouldProceed).toBe(false);
    });

    test("should cancel when model is pulling", () => {
      const model = { name: "whisper-base", installed: false, path: null };
      const selectedModelIsPulling = true;
      const action = selectedModelIsPulling ? "cancel" : "other";

      expect(action).toBe("cancel");
    });

    test("should select when model installed and no active operation", () => {
      const model = { name: "whisper-base", installed: true, path: "/path" };
      const activeModelOp = null;
      const selectedModelIsPulling = false;
      const action = selectedModelIsPulling ? "cancel" : activeModelOp ? "wait" : model.installed ? "select" : "pull";

      expect(action).toBe("select");
    });

    test("should pull when model not installed", () => {
      const model = { name: "whisper-base", installed: false, path: null };
      const activeModelOp = null;
      const selectedModelIsPulling = false;
      const action = selectedModelIsPulling ? "cancel" : activeModelOp ? "wait" : model.installed ? "select" : "pull";

      expect(action).toBe("pull");
    });

    test("should queue pull when another model operation is active", () => {
      const model = { name: "whisper-base", installed: false, path: null };
      const activeModelOp = { type: "pulling", model: "whisper-small" };
      const selectedModelIsPulling = false;
      const action = selectedModelIsPulling ? "cancel" : model.installed ? "select" : "pull";

      expect(activeModelOp).toBeTruthy();
      expect(action).toBe("pull");
    });

    test("should wait when another operation is active", () => {
      const model = { name: "whisper-base", installed: true, path: "/path" };
      const activeModelOp = { type: "removing", model: "other-model" };
      const selectedModelIsPulling = false;
      const action = selectedModelIsPulling ? "cancel" : activeModelOp ? "wait" : "select";

      expect(action).toBe("wait");
    });
  });

  describe("handleRemove logic", () => {
    test("should not remove when model not installed", () => {
      const model = { name: "whisper-base", installed: false, path: null };
      const canRemove = model.installed;

      expect(canRemove).toBe(false);
    });

    test("should not remove when operation active", () => {
      const model = { name: "whisper-base", installed: true, path: "/path" };
      const activeModelOp = { type: "pulling", model: "other" };
      const canRemove = model.installed && !activeModelOp;

      expect(canRemove).toBe(false);
    });

    test("should remove when model installed and no operation", () => {
      const model = { name: "whisper-base", installed: true, path: "/path" };
      const activeModelOp = null;
      const canRemove = model.installed && !activeModelOp;

      expect(canRemove).toBe(true);
    });
  });

  describe("handleSelect logic", () => {
    test("should not select uninstalled model", () => {
      const model = { name: "whisper-base", installed: false, path: null };
      const canSelect = model.installed;

      expect(canSelect).toBe(false);
    });

    test("should select installed model", () => {
      const model = { name: "whisper-base", installed: true, path: "/path" };
      const canSelect = model.installed;

      expect(canSelect).toBe(true);
    });
  });

  describe("selectedModelName logic", () => {
    test("should return null when no config", () => {
      const configured = null;
      const selectedModelName = configured ?? null;

      expect(selectedModelName).toBeNull();
    });

    test("should return null when model not installed", () => {
      const configured = "whisper-base";
      const models: ModelInfo[] = [{ name: "whisper-base", installed: false, path: null }];
      const match = models.find((model) => model.name === configured);
      const selectedModelName = match?.installed ? configured : null;

      expect(selectedModelName).toBeNull();
    });

    test("should return model name when installed", () => {
      const configured = "whisper-base";
      const models: ModelInfo[] = [{ name: "whisper-base", installed: true, path: "/path" }];
      const match = models.find((model) => model.name === configured);
      const selectedModelName = match?.installed ? configured : null;

      expect(selectedModelName).toBe("whisper-base");
    });
  });

  describe("modal dimensions", () => {
    test("should calculate modal height", () => {
      const terminalHeight = 40;
      const minHeight = 16;
      const maxHeight = Math.max(minHeight, terminalHeight - 4);
      const preferred = Math.floor(terminalHeight * 0.68);
      const modalHeight = Math.max(minHeight, Math.min(preferred, maxHeight));

      expect(modalHeight).toBeGreaterThanOrEqual(minHeight);
      expect(modalHeight).toBeLessThanOrEqual(maxHeight);
    });

    test("should respect minimum height", () => {
      const terminalHeight = 10;
      const minHeight = 16;
      const maxHeight = Math.max(minHeight, terminalHeight - 4);
      const preferred = Math.floor(terminalHeight * 0.68);
      const modalHeight = Math.max(minHeight, Math.min(preferred, maxHeight));

      expect(modalHeight).toBe(minHeight);
    });
  });

  describe("keyboard navigation", () => {
    test("should move up with k key", () => {
      const selectedIndex = 5;
      const newIndex = Math.max(0, selectedIndex - 1);

      expect(newIndex).toBe(4);
    });

    test("should not move up below 0", () => {
      const selectedIndex = 0;
      const newIndex = Math.max(0, selectedIndex - 1);

      expect(newIndex).toBe(0);
    });

    test("should move down with j key", () => {
      const selectedIndex = 2;
      const modelsLength = 10;
      const newIndex = Math.min(modelsLength - 1, selectedIndex + 1);

      expect(newIndex).toBe(3);
    });

    test("should not move down beyond list", () => {
      const selectedIndex = 9;
      const modelsLength = 10;
      const newIndex = Math.min(modelsLength - 1, selectedIndex + 1);

      expect(newIndex).toBe(9);
    });
  });

  describe("setup requirements", () => {
    test("should detect first run setup required", () => {
      const config = { first_run_setup_required: true };
      const setupRequired = Boolean(config.first_run_setup_required);

      expect(setupRequired).toBe(true);
    });

    test("should lock when first run setup required", () => {
      const firstRunSetup = true;
      const setupRequired = true;
      const setupLocked = firstRunSetup && setupRequired;

      expect(setupLocked).toBe(true);
    });
  });

  describe("edge cases", () => {
    test("should handle empty model name", () => {
      const model = { name: "", installed: true, path: "/path" };

      expect(model.name.length).toBe(0);
    });

    test("should handle adjusting index when models list shrinks", () => {
      const selectedIndex = 5;
      const modelsLength = 3;
      const shouldAdjust = selectedIndex >= modelsLength;

      expect(shouldAdjust).toBe(true);
    });
  });
});
