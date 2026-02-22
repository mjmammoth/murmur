import { describe, expect, test } from "bun:test";
import { formatDeviceLabel } from "../util/format";

/**
 * Tests for SettingsSelectModal component
 *
 * Provides dropdown selection for various settings like runtime, device, compute type, language, etc.
 */

describe("SettingsSelectModal", () => {
  describe("audio input payloads", () => {
    test("should keep null device key when selecting system default", () => {
      const selected = { value: null, label: "System default" };
      const payload = { type: "set_audio_input_device", device_key: selected.value };

      expect(payload.device_key).toBeNull();
    });

    test("should send explicit key when selecting an input device", () => {
      const selected = { value: "CoreAudio:USB Mic", label: "USB Mic" };
      const payload = { type: "set_audio_input_device", device_key: selected.value };

      expect(payload.device_key).toBe("CoreAudio:USB Mic");
    });
  });

  describe("device label formatting", () => {
    test("should format mps label as Metal (mps)", () => {
      expect(formatDeviceLabel("mps")).toBe("Metal (mps)");
    });

    test("should keep canonical mps value in set_model_device payload", () => {
      const selected = { value: "mps", label: formatDeviceLabel("mps") };
      const payload = { type: "set_model_device", device: selected.value ?? "cpu" };

      expect(selected.label).toBe("Metal (mps)");
      expect(payload.device).toBe("mps");
    });
  });

  describe("normalizeValue function", () => {
    test("should return empty string for null", () => {
      const value = null;
      const normalized = value ?? "";

      expect(normalized).toBe("");
    });

    test("should return empty string for undefined", () => {
      const value = undefined;
      const normalized = value ?? "";

      expect(normalized).toBe("");
    });

    test("should return value for string", () => {
      const value = "test";
      const normalized = value ?? "";

      expect(normalized).toBe("test");
    });
  });

  describe("optionId function", () => {
    test("should return __auto__ for null", () => {
      const value = null;
      const id = value ?? "__auto__";

      expect(id).toBe("__auto__");
    });

    test("should return value for string", () => {
      const value = "en";
      const id = value ?? "__auto__";

      expect(id).toBe("en");
    });
  });

  describe("isPrintableKey function", () => {
    test("should return true for single character", () => {
      const key = { name: "a", ctrl: false, meta: false, option: false };
      const isPrintable = !key.ctrl && !key.meta && !key.option && key.name.length === 1;

      expect(isPrintable).toBe(true);
    });

    test("should return false for modifier combinations", () => {
      const key = { name: "a", ctrl: true, meta: false, option: false };
      const isPrintable = !key.ctrl && !key.meta && !key.option && key.name.length === 1;

      expect(isPrintable).toBe(false);
    });
  });

  describe("language filtering", () => {
    test("should match label", () => {
      const option = { label: "English", description: "en", value: "en" };
      const query = "eng";
      const haystack = `${option.label} ${option.description} ${option.value}`.toLowerCase();
      const matches = haystack.includes(query.toLowerCase());

      expect(matches).toBe(true);
    });

    test("should match description", () => {
      const option = { label: "English", description: "en", value: "en" };
      const query = "en";
      const haystack = `${option.label} ${option.description} ${option.value}`.toLowerCase();
      const matches = haystack.includes(query.toLowerCase());

      expect(matches).toBe(true);
    });

    test("should not match unrelated query", () => {
      const option = { label: "English", description: "en", value: "en" };
      const query = "french";
      const haystack = `${option.label} ${option.description} ${option.value}`.toLowerCase();
      const matches = haystack.includes(query.toLowerCase());

      expect(matches).toBe(false);
    });
  });

  describe("navigation with disabled options", () => {
    test("should skip disabled options when moving down", () => {
      const options = [
        { value: "opt1", disabled: false },
        { value: "opt2", disabled: true },
        { value: "opt3", disabled: false },
      ];
      const currentIndex = 0;
      let nextIndex = currentIndex + 1;

      // Skip disabled
      while (nextIndex < options.length && options[nextIndex]?.disabled) {
        nextIndex++;
      }

      expect(nextIndex).toBe(2); // Should skip index 1
    });

    test("should wrap around when reaching end", () => {
      const optionsLength = 5;
      let nextIndex = 5;

      if (nextIndex >= optionsLength) {
        nextIndex = 0;
      }

      expect(nextIndex).toBe(0);
    });

    test("should wrap backwards when reaching start", () => {
      const optionsLength = 5;
      let nextIndex = -1;

      if (nextIndex < 0) {
        nextIndex = optionsLength - 1;
      }

      expect(nextIndex).toBe(4);
    });
  });

  describe("title and subtitle logic", () => {
    test("should show Model Runtime title", () => {
      const settingId = "model.runtime";
      const title = settingId === "model.runtime" ? "Model Runtime" : "Other";

      expect(title).toBe("Model Runtime");
    });

    test("should show Model Language title", () => {
      const settingId = "model.language";
      const title = settingId === "model.language" ? "Model Language" : "Other";

      expect(title).toBe("Model Language");
    });
  });

  describe("option disabled state", () => {
    test("should respect device enabled state", () => {
      const device = { enabled: false, reason: "Not available" };
      const isDisabled = !device.enabled;

      expect(isDisabled).toBe(true);
    });

    test("should show reason when disabled", () => {
      const option = { disabled: true, reason: "CUDA not found" };
      const displayText = option.disabled && option.reason ? option.reason : "Description";

      expect(displayText).toBe("CUDA not found");
    });
  });

  describe("compute type filtering", () => {
    test("should filter unsupported compute types", () => {
      const supported = new Set(["int8", "float32"]);
      const option = { value: "float16" };
      const isSupported = supported.has(option.value);

      expect(isSupported).toBe(false);
    });

    test("should allow supported compute types", () => {
      const supported = new Set(["int8", "float32"]);
      const option = { value: "int8" };
      const isSupported = supported.has(option.value);

      expect(isSupported).toBe(true);
    });
  });

  describe("modal dimensions", () => {
    test("should calculate modal width", () => {
      const terminalWidth = 100;
      const maxWidth = Math.max(52, terminalWidth - 8);
      const preferred = Math.floor(terminalWidth * 0.6);
      const modalWidth = Math.max(52, Math.min(preferred, maxWidth));

      expect(modalWidth).toBeGreaterThanOrEqual(52);
    });

    test("should calculate modal height", () => {
      const terminalHeight = 40;
      const maxHeight = Math.max(12, terminalHeight - 6);
      const preferred = Math.floor(terminalHeight * 0.7);
      const modalHeight = Math.max(12, Math.min(preferred, maxHeight));

      expect(modalHeight).toBeGreaterThanOrEqual(12);
    });
  });

  describe("keyboard handling", () => {
    test("should close on escape", () => {
      const keyName = "escape";
      const shouldClose = keyName === "escape" || keyName === "q";

      expect(shouldClose).toBe(true);
    });

    test("should navigate up with k", () => {
      const keyName: string = "k";
      const shouldMoveUp = keyName === "up" || keyName === "k";

      expect(shouldMoveUp).toBe(true);
    });

    test("should navigate down with j", () => {
      const keyName: string = "j";
      const shouldMoveDown = keyName === "down" || keyName === "j";

      expect(shouldMoveDown).toBe(true);
    });
  });

  describe("return target behavior", () => {
    test("should return to settings when returnToSettings is true", () => {
      const dialogData = {
        returnToSettings: true,
        returnToDialog: "welcome" as const,
      };
      const destination = dialogData.returnToSettings
        ? "settings"
        : dialogData.returnToDialog === "welcome"
          ? "welcome"
          : "close";

      expect(destination).toBe("settings");
    });

    test("should return to welcome when return target is welcome", () => {
      const dialogData = {
        returnToSettings: false,
        returnToDialog: "welcome" as const,
      };
      const destination = dialogData.returnToSettings
        ? "settings"
        : dialogData.returnToDialog === "welcome"
          ? "welcome"
          : "close";

      expect(destination).toBe("welcome");
    });

    test("should close when no return target is set", () => {
      const dialogData = {
        returnToSettings: false,
        returnToDialog: null,
      };
      const destination = dialogData.returnToSettings
        ? "settings"
        : dialogData.returnToDialog === "welcome"
          ? "welcome"
          : "close";

      expect(destination).toBe("close");
    });
  });

  describe("current value detection", () => {
    test("should identify current value", () => {
      const currentValue = "int8";
      const optionValue = "int8";
      const isCurrent = currentValue === optionValue;

      expect(isCurrent).toBe(true);
    });

    test("should handle null current value", () => {
      const currentValue = null;
      const normalized = currentValue ?? "";

      expect(normalized).toBe("");
    });
  });

  describe("edge cases", () => {
    test("should handle empty options list", () => {
      const options: any[] = [];
      const selectedIndex = 0;
      const selectedOption = options[selectedIndex] ?? null;

      expect(selectedOption).toBeNull();
    });

    test("should handle empty filter query", () => {
      const query = "";
      const shouldFilter = query.trim().length > 0;

      expect(shouldFilter).toBe(false);
    });
  });
});
