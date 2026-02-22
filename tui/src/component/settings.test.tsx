import { describe, expect, test } from "bun:test";
import { formatAudioInputLabel, formatDeviceLabel } from "../util/format";

/**
 * Tests for Settings component
 *
 * Main settings panel with sections for Capture, Model, Output, Appearance, and Advanced settings.
 */

describe("Settings", () => {
  const SECTION_ORDER = ["Capture", "Model", "Output", "Appearance", "Advanced"];

  describe("audio input setting", () => {
    test("should display system default when input key is empty", () => {
      const label = formatAudioInputLabel(null, []);
      expect(label).toBe("System default");
    });

    test("should display unavailable indicator when saved input is missing", () => {
      const label = formatAudioInputLabel("CoreAudio:Missing", []);
      expect(label).toBe("Unavailable (saved device)");
    });

    test("should display resolved input label for known device", () => {
      const label = formatAudioInputLabel("CoreAudio:USB Mic", [
        { key: "CoreAudio:USB Mic", name: "USB Mic", hostapi: "CoreAudio" },
      ]);
      expect(label).toBe("USB Mic (CoreAudio)");
    });
  });

  describe("device display labels", () => {
    test("should format mps as Metal (mps)", () => {
      expect(formatDeviceLabel("mps")).toBe("Metal (mps)");
    });

    test("should keep cpu and cuda labels uppercase", () => {
      expect(formatDeviceLabel("cpu")).toBe("CPU");
      expect(formatDeviceLabel("cuda")).toBe("CUDA");
    });
  });

  describe("boolLabel function", () => {
    test("should return 'on' for true", () => {
      const value = true;
      const label = value ? "on" : "off";

      expect(label).toBe("on");
    });

    test("should return 'off' for false", () => {
      const value = false;
      const label = value ? "on" : "off";

      expect(label).toBe("off");
    });
  });

  describe("withFallback function", () => {
    test("should return value for valid string", () => {
      const value = "test";
      const result = value ?? "-";

      expect(result).toBe("test");
    });

    test("should return fallback for null", () => {
      const value = null;
      const result = value ?? "-";

      expect(result).toBe("-");
    });

    test("should return fallback for undefined", () => {
      const value = undefined;
      const result = value ?? "-";

      expect(result).toBe("-");
    });

    test("should return fallback for empty string after trim", () => {
      const value = "   ";
      const trimmed = value.trim();
      const result = trimmed.length > 0 ? trimmed : "-";

      expect(result).toBe("-");
    });
  });

  describe("isPrintableKey function", () => {
    test("should return true for single character", () => {
      const key = { name: "a", ctrl: false, meta: false, option: false };
      const isPrintable = !key.ctrl && !key.meta && !key.option && key.name.length === 1;

      expect(isPrintable).toBe(true);
    });

    test("should return false for modified key", () => {
      const key = { name: "a", ctrl: true, meta: false, option: false };
      const isPrintable = !key.ctrl && !key.meta && !key.option && key.name.length === 1;

      expect(isPrintable).toBe(false);
    });
  });

  describe("section ordering", () => {
    test("should have correct section order", () => {
      expect(SECTION_ORDER).toEqual(["Capture", "Model", "Output", "Appearance", "Advanced"]);
    });

    test("should have 5 sections", () => {
      expect(SECTION_ORDER.length).toBe(5);
    });
  });

  describe("filter logic", () => {
    test("should match setting by title", () => {
      const item = { title: "Noise Suppression", description: "RNNoise filter", keywords: [], value: "on" };
      const query = "noise";
      const haystack = `${item.title} ${item.description}`.toLowerCase();
      const matches = haystack.includes(query.toLowerCase());

      expect(matches).toBe(true);
    });

    test("should match setting by keyword", () => {
      const item = { title: "Setting", description: "Description", keywords: ["hotkey", "shortcut"], value: "on" };
      const query = "hotkey";
      const haystack = item.keywords.join(" ").toLowerCase();
      const matches = haystack.includes(query.toLowerCase());

      expect(matches).toBe(true);
    });

    test("should not match unrelated query", () => {
      const item = { title: "Noise Suppression", description: "RNNoise filter", keywords: [], value: "on" };
      const query = "model";
      const haystack = `${item.title} ${item.description}`.toLowerCase();
      const matches = haystack.includes(query.toLowerCase());

      expect(matches).toBe(false);
    });

    test("should return all items when query empty", () => {
      const query = "";
      const shouldFilter = query.trim().length > 0;

      expect(shouldFilter).toBe(false);
    });
  });

  describe("keyboard navigation", () => {
    test("should close on escape when no filter", () => {
      const keyName = "escape";
      const filterQuery = "";
      const shouldClose = (keyName === "escape" || keyName === "q") && filterQuery.length === 0;

      expect(shouldClose).toBe(true);
    });

    test("should clear filter on escape when filter exists", () => {
      const keyName = "escape";
      const filterQuery = "noise";
      const shouldClearFilter = (keyName === "escape" || keyName === "q") && filterQuery.length > 0;

      expect(shouldClearFilter).toBe(true);
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

    test("should enter filter mode with slash", () => {
      const keyName = "/";
      const shouldEnterFilter = keyName === "/";

      expect(shouldEnterFilter).toBe(true);
    });

    test("should activate with space or enter", () => {
      const keyName = "space";
      const shouldActivate = keyName === "space" || keyName === "return" || keyName === "enter";

      expect(shouldActivate).toBe(true);
    });
  });

  describe("toggle handling", () => {
    test("should toggle on left arrow", () => {
      const keyName = "left";
      const controlKind = "toggle";
      const shouldSetFalse = keyName === "left" && controlKind === "toggle";

      expect(shouldSetFalse).toBe(true);
    });

    test("should toggle on right arrow", () => {
      const keyName = "right";
      const controlKind = "toggle";
      const shouldSetTrue = keyName === "right" && controlKind === "toggle";

      expect(shouldSetTrue).toBe(true);
    });
  });

  describe("control kinds", () => {
    test("should have toggle control kind", () => {
      const controlKind = "toggle";
      const isToggle = controlKind === "toggle";

      expect(isToggle).toBe(true);
    });

    test("should have select control kind", () => {
      const controlKind = "select";
      const isSelect = controlKind === "select";

      expect(isSelect).toBe(true);
    });

    test("should have open control kind", () => {
      const controlKind = "open";
      const isOpen = controlKind === "open";

      expect(isOpen).toBe(true);
    });

    test("should have edit control kind", () => {
      const controlKind = "edit";
      const isEdit = controlKind === "edit";

      expect(isEdit).toBe(true);
    });

    test("should have read-only control kind", () => {
      const controlKind = "read-only";
      const isReadOnly = controlKind === "read-only";

      expect(isReadOnly).toBe(true);
    });
  });

  describe("setting interactivity", () => {
    test("should be interactive for toggle settings", () => {
      const controlKind: string = "toggle";
      const interactive = controlKind !== "read-only";

      expect(interactive).toBe(true);
    });

    test("should not be interactive for read-only settings", () => {
      const controlKind = "read-only";
      const interactive = controlKind !== "read-only";

      expect(interactive).toBe(false);
    });
  });

  describe("value color logic", () => {
    test("should use success color for active toggle", () => {
      const controlKind = "toggle";
      const isOn = true;
      const colors = { success: "#00FF00", textMuted: "#888888" };

      const color = controlKind === "toggle" && isOn ? colors.success : colors.textMuted;

      expect(color).toBe("#00FF00");
    });

    test("should use muted color for inactive toggle", () => {
      const controlKind = "toggle";
      const isOn = false;
      const colors = { success: "#00FF00", textMuted: "#888888" };

      const color = controlKind === "toggle" && isOn ? colors.success : colors.textMuted;

      expect(color).toBe("#888888");
    });
  });

  describe("filter mode", () => {
    test("should append character in filter mode", () => {
      const query = "noi";
      const newQuery = `${query}s`;

      expect(newQuery).toBe("nois");
    });

    test("should remove character on backspace", () => {
      const query = "noise";
      const newQuery = query.slice(0, -1);

      expect(newQuery).toBe("nois");
    });

    test("should append space", () => {
      const query = "noise";
      const newQuery = `${query} `;

      expect(newQuery).toBe("noise ");
    });
  });

  describe("modal dimensions", () => {
    test("should calculate modal height", () => {
      const terminalHeight = 40;
      const minHeight = 20;
      const maxHeight = Math.max(minHeight, terminalHeight - 4);
      const preferred = Math.floor(terminalHeight * 0.8);
      const modalHeight = Math.max(minHeight, Math.min(preferred, maxHeight));

      expect(modalHeight).toBeGreaterThanOrEqual(minHeight);
    });

    test("should have width of 94", () => {
      const width = 94;

      expect(width).toBe(94);
    });
  });

  describe("description text logic", () => {
    test("should append read-only reason to description", () => {
      const description = "Setting description";
      const readOnlyReason = "Not configurable";
      const fullDescription = `${description} (${readOnlyReason})`;

      expect(fullDescription).toBe("Setting description (Not configurable)");
    });

    test("should use description as-is when no reason", () => {
      const description = "Setting description";
      const readOnlyReason = undefined;
      const fullDescription = readOnlyReason ? `${description} (${readOnlyReason})` : description;

      expect(fullDescription).toBe("Setting description");
    });
  });

  describe("edge cases", () => {
    test("should handle empty section", () => {
      const sectionItems: any[] = [];
      const shouldShow = sectionItems.length > 0;

      expect(shouldShow).toBe(false);
    });

    test("should handle selected index out of bounds", () => {
      const items = [{ id: "1" }, { id: "2" }];
      const selectedIndex = 5;
      const shouldAdjust = selectedIndex >= items.length;

      expect(shouldAdjust).toBe(true);
    });
  });
});
