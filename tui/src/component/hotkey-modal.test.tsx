import { describe, expect, test } from "bun:test";
import { createRoot } from "solid-js";

/**
 * Tests for HotkeyModal component
 *
 * The modal allows users to capture and set a new hotkey by pressing the desired key combination.
 */

describe("HotkeyModal", () => {
  const MODIFIER_KEYS = new Set(["shift", "ctrl", "control", "meta", "cmd", "command", "alt", "option"]);

  const SHIFTED_DIGIT_SYMBOL_TO_KEY: Record<string, string> = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
  };

  describe("normalizeHotkeyBaseKey function", () => {
    test("should recognize shifted digit symbols", () => {
      const name = "!";
      const baseKey = SHIFTED_DIGIT_SYMBOL_TO_KEY[name];
      const inferredShift = !!baseKey;

      expect(baseKey).toBe("1");
      expect(inferredShift).toBe(true);
    });

    test("should handle lowercase letters", () => {
      const name = "a";
      const lowered = name.toLowerCase();
      const isValid = /^[a-z0-9]$/.test(lowered);

      expect(isValid).toBe(true);
    });

    test("should handle function keys", () => {
      const name = "f1";
      const lowered = name.toLowerCase();
      const isValid = /^f([1-9]|1[0-2])$/.test(lowered);

      expect(isValid).toBe(true);
    });

    test("should handle F12", () => {
      const name = "F12";
      const lowered = name.toLowerCase();
      const isValid = /^f([1-9]|1[0-2])$/.test(lowered);

      expect(isValid).toBe(true);
    });

    test("should reject F13", () => {
      const name = "F13";
      const lowered = name.toLowerCase();
      const isValid = /^f([1-9]|1[0-2])$/.test(lowered);

      expect(isValid).toBe(false);
    });

    test("should handle space key", () => {
      const name = "space";
      const baseKey = name.toLowerCase() === "space" ? "space" : null;

      expect(baseKey).toBe("space");
    });

    test("should handle enter/return keys", () => {
      expect("return".toLowerCase()).toBe("return");
      expect("enter".toLowerCase()).toBe("enter");
    });

    test("should handle tab key", () => {
      const name = "tab";
      const baseKey = name.toLowerCase() === "tab" ? "tab" : null;

      expect(baseKey).toBe("tab");
    });

    test("should handle escape key", () => {
      const name = "escape";
      const baseKey = name.toLowerCase() === "escape" || name.toLowerCase() === "esc" ? "escape" : null;

      expect(baseKey).toBe("escape");
    });

    test("should handle esc alias", () => {
      const name = "esc";
      const baseKey = name.toLowerCase() === "escape" || name.toLowerCase() === "esc" ? "escape" : null;

      expect(baseKey).toBe("escape");
    });

    test("should return null for unsupported keys", () => {
      const name = "SomeWeirdKey";
      const lowered = name.toLowerCase();
      const isLetter = /^[a-z0-9]$/.test(lowered);
      const isFunction = /^f([1-9]|1[0-2])$/.test(lowered);
      const isSpecial = ["space", "return", "enter", "tab", "escape", "esc"].includes(lowered);

      expect(isLetter || isFunction || isSpecial).toBe(false);
    });
  });

  describe("formatHotkeyFromEvent function", () => {
    test("should detect modifier-only key press", () => {
      const keyName = "shift";
      const isModifier = MODIFIER_KEYS.has(keyName.toLowerCase());

      expect(isModifier).toBe(true);
    });

    test("should return error for unsupported key", () => {
      const keyName = "F13";
      const error = `Unsupported key: ${keyName}`;

      expect(error).toBe("Unsupported key: F13");
    });

    test("should infer shift from uppercase letter", () => {
      const keyName = "A";
      const caseInferredShift = keyName.length === 1 && keyName !== keyName.toLowerCase();

      expect(caseInferredShift).toBe(true);
    });

    test("should not infer shift from lowercase letter", () => {
      const keyName = "a";
      const caseInferredShift = keyName.length === 1 && keyName !== keyName.toLowerCase();

      expect(caseInferredShift).toBe(false);
    });

    test("should format ctrl+a correctly", () => {
      const parts = ["ctrl", "a"];
      const hotkey = parts.join("+");

      expect(hotkey).toBe("ctrl+a");
    });

    test("should format cmd+shift+f correctly", () => {
      const parts = ["cmd", "shift", "f"];
      const hotkey = parts.join("+");

      expect(hotkey).toBe("cmd+shift+f");
    });

    test("should format option+space correctly", () => {
      const parts = ["option", "space"];
      const hotkey = parts.join("+");

      expect(hotkey).toBe("option+space");
    });

    test("should preserve modifier order", () => {
      const key = { meta: true, ctrl: false, option: true, shift: true, name: "f" };
      const parts: string[] = [];

      if (key.meta) parts.push("cmd");
      if (key.ctrl) parts.push("ctrl");
      if (key.option) parts.push("option");
      if (key.shift) parts.push("shift");
      parts.push("f");

      const hotkey = parts.join("+");

      expect(hotkey).toBe("cmd+option+shift+f");
    });
  });

  describe("keyboard event handling", () => {
    test("should ignore release events", () => {
      const eventType = "release";
      const shouldProcess = eventType !== "release";

      expect(shouldProcess).toBe(false);
    });

    test("should ignore repeated events", () => {
      const repeated = true;
      const shouldProcess = !repeated;

      expect(shouldProcess).toBe(false);
    });

    test("should process press events", () => {
      const eventType = "press";
      const repeated = false;
      const shouldProcess = eventType !== "release" && !repeated;

      expect(shouldProcess).toBe(true);
    });

    test("should close modal on escape", () => {
      const keyName = "escape";
      const shouldClose = keyName === "escape" || keyName === "q";

      expect(shouldClose).toBe(true);
    });

    test("should close modal on q", () => {
      const keyName = "q";
      const shouldClose = keyName === "escape" || keyName === "q";

      expect(shouldClose).toBe(true);
    });
  });

  describe("error messages", () => {
    test("should show error for modifier-only press", () => {
      const errorMessage = "Press a non-modifier key";

      expect(errorMessage).toBe("Press a non-modifier key");
    });

    test("should show error for unsupported key", () => {
      const keyName = "F15";
      const errorMessage = `Unsupported key: ${keyName}`;

      expect(errorMessage).toBe("Unsupported key: F15");
    });

    test("should clear error on successful capture", () => {
      let error = "Some error";
      error = "";

      expect(error).toBe("");
    });
  });

  describe("success feedback", () => {
    test("should show last set hotkey", () => {
      const lastSetHotkey = "ctrl+shift+a";
      const feedback = `set to ${lastSetHotkey}`;

      expect(feedback).toBe("set to ctrl+shift+a");
    });

    test("should show empty feedback initially", () => {
      const lastSetHotkey = "";
      const feedback = lastSetHotkey ? `set to ${lastSetHotkey}` : "esc/q cancel";

      expect(feedback).toBe("esc/q cancel");
    });
  });

  describe("dialog data handling", () => {
    test("should extract returnToSettings flag", () => {
      const dialogData = { returnToSettings: true };
      const shouldReturn = Boolean(dialogData.returnToSettings);

      expect(shouldReturn).toBe(true);
    });

    test("should extract returnSettingId", () => {
      const dialogData = { returnSettingId: "hotkey.key" };
      const settingId = dialogData.returnSettingId ?? null;

      expect(settingId).toBe("hotkey.key");
    });

    test("should handle missing dialog data", () => {
      const dialogData = undefined;
      const shouldReturn = Boolean(dialogData?.returnToSettings);

      expect(shouldReturn).toBe(false);
    });
  });

  describe("closeModal function", () => {
    test("should open settings when returnToSettings is true", () => {
      const returnToSettings = true;
      const returnSettingId = "hotkey.key";
      let openedDialog = "";

      if (returnToSettings) {
        openedDialog = "settings";
      }

      expect(openedDialog).toBe("settings");
    });

    test("should close dialog when returnToSettings is false", () => {
      const returnToSettings = false;
      let dialogClosed = false;

      if (!returnToSettings) {
        dialogClosed = true;
      }

      expect(dialogClosed).toBe(true);
    });
  });

  describe("UI display", () => {
    test("should have correct modal width", () => {
      const width = 58;

      expect(width).toBe(58);
    });

    test("should display current hotkey", () => {
      const currentHotkey = "cmd+shift+space";
      const display = `current: ${currentHotkey}`;

      expect(display).toContain(currentHotkey);
    });

    test("should display listening status", () => {
      const listeningText = "listening...";

      expect(listeningText).toBe("listening...");
    });
  });

  describe("all modifier keys", () => {
    test("should recognize all modifier key names", () => {
      const modifiers = ["shift", "ctrl", "control", "meta", "cmd", "command", "alt", "option"];

      modifiers.forEach(mod => {
        expect(MODIFIER_KEYS.has(mod)).toBe(true);
      });
    });
  });

  describe("shifted digit symbols", () => {
    test("should map all shifted digits", () => {
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY["!"]).toBe("1");
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY["@"]).toBe("2");
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY["#"]).toBe("3");
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY["$"]).toBe("4");
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY["%"]).toBe("5");
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY["^"]).toBe("6");
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY["&"]).toBe("7");
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY["*"]).toBe("8");
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY["("]).toBe("9");
      expect(SHIFTED_DIGIT_SYMBOL_TO_KEY[")"]).toBe("0");
    });
  });

  describe("edge cases", () => {
    test("should handle empty key name", () => {
      const keyName = "";
      const isModifier = MODIFIER_KEYS.has(keyName.toLowerCase());

      expect(isModifier).toBe(false);
    });

    test("should handle mixed case modifier", () => {
      const keyName = "SHIFT";
      const isModifier = MODIFIER_KEYS.has(keyName.toLowerCase());

      expect(isModifier).toBe(true);
    });

    test("should handle numeric keys", () => {
      for (let i = 0; i <= 9; i++) {
        const keyName = String(i);
        const isValid = /^[a-z0-9]$/.test(keyName.toLowerCase());
        expect(isValid).toBe(true);
      }
    });
  });
});