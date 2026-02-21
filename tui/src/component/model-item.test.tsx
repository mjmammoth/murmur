import { describe, expect, test } from "bun:test";
import type { RuntimeName } from "../types";
import { formatBytes } from "../util/format";

interface StatusToken {
  text: string;
  color: string;
}

interface TokenInputs {
  opType: "pulling" | "removing" | null;
  opRuntime: RuntimeName | null;
  isQueued: boolean;
  isSelectedModel: boolean;
  activeRuntime: RuntimeName;
  installed: boolean;
  spinner: string;
  progressPercent: number | null;
}

function buildSizeLabel(sizeBytes: number | null, estimated = false): string {
  if (typeof sizeBytes !== "number" || sizeBytes <= 0) return "-";
  const prefix = estimated ? "~" : "";
  return `${prefix}${formatBytes(sizeBytes)}`;
}

function runtimeToken(inputs: TokenInputs): StatusToken {
  const colors = {
    transcribing: "#f5a742",
    warning: "#e06c75",
    accent: "#9d7cd8",
    secondary: "#5c9cf5",
    textDim: "#606060",
  };

  if (inputs.opType && inputs.opRuntime === inputs.activeRuntime) {
    if (inputs.opType === "pulling") {
      if (typeof inputs.progressPercent === "number") {
        const percent = Math.max(0, Math.min(100, Math.round(inputs.progressPercent)));
        return { text: `${inputs.spinner}${percent}%`, color: colors.transcribing };
      }
      return { text: `${inputs.spinner}pull`, color: colors.transcribing };
    }
    return { text: `${inputs.spinner}rm`, color: colors.warning };
  }

  if (inputs.isQueued) {
    return { text: "queued", color: colors.accent };
  }

  if (inputs.installed) {
    return { text: "●", color: colors.secondary };
  }

  return { text: "○", color: colors.textDim };
}

function selectedRowColor(inputs: {
  themeId: string;
  isSelectedModel: boolean;
  isFocusedRow: boolean;
}): string | null {
  const subtleByTheme: Record<string, string> = {
    dark: "#1f3a2f",
    light: "#d7efe3",
    "catppuccin-mocha": "#243a31",
    "catppuccin-latte": "#cadfce",
  };
  const brightByTheme: Record<string, string> = {
    dark: "#2b4d3f",
    light: "#b8ddca",
    "catppuccin-mocha": "#315146",
    "catppuccin-latte": "#afd0ba",
  };

  if (!inputs.isSelectedModel) return null;
  if (inputs.isFocusedRow) return brightByTheme[inputs.themeId] ?? "#1e1e1e";
  return subtleByTheme[inputs.themeId] ?? "#282828";
}

describe("ModelItem", () => {
  describe("size label formatting", () => {
    test("shows an estimated size with a tilde prefix", () => {
      const label = buildSizeLabel(1600 * 1024 * 1024, true);

      expect(label.startsWith("~")).toBe(true);
      expect(label).toContain("GB");
    });

    test("shows an exact size without a tilde prefix", () => {
      const label = buildSizeLabel(500 * 1024 * 1024, false);

      expect(label.startsWith("~")).toBe(false);
      expect(label).toContain("MB");
    });

    test("shows '-' when size is unavailable", () => {
      expect(buildSizeLabel(null)).toBe("-");
      expect(buildSizeLabel(0)).toBe("-");
    });

    test("does not include delta percentage text", () => {
      const label = buildSizeLabel(1500 * 1024 * 1024, false);

      expect(label.includes("(")).toBe(false);
      expect(label.includes("%")).toBe(false);
    });
  });

  describe("runtime status cells", () => {
    test("pulling state shows spinner + percent and transcribing color", () => {
      const token = runtimeToken({
        opType: "pulling",
        opRuntime: "faster-whisper",
        isQueued: false,
        isSelectedModel: false,
        activeRuntime: "faster-whisper",
        installed: false,
        spinner: "|",
        progressPercent: 42,
      });

      expect(token).toEqual({ text: "|42%", color: "#f5a742" });
    });

    test("queued state is highlighted with accent color", () => {
      const token = runtimeToken({
        opType: null,
        opRuntime: null,
        isQueued: true,
        isSelectedModel: false,
        activeRuntime: "faster-whisper",
        installed: false,
        spinner: "|",
        progressPercent: null,
      });

      expect(token).toEqual({ text: "queued", color: "#9d7cd8" });
    });

    test("selected active runtime shows a blue dot (row carries green highlight)", () => {
      const token = runtimeToken({
        opType: null,
        opRuntime: null,
        isQueued: false,
        isSelectedModel: true,
        activeRuntime: "faster-whisper",
        installed: true,
        spinner: "|",
        progressPercent: null,
      });

      expect(token).toEqual({ text: "●", color: "#5c9cf5" });
    });

    test("installed idle state shows a solid blue dot", () => {
      const token = runtimeToken({
        opType: null,
        opRuntime: null,
        isQueued: false,
        isSelectedModel: false,
        activeRuntime: "faster-whisper",
        installed: true,
        spinner: "|",
        progressPercent: null,
      });

      expect(token).toEqual({ text: "●", color: "#5c9cf5" });
    });

    test("not-installed state shows a hollow dim dot", () => {
      const token = runtimeToken({
        opType: null,
        opRuntime: null,
        isQueued: false,
        isSelectedModel: false,
        activeRuntime: "faster-whisper",
        installed: false,
        spinner: "|",
        progressPercent: null,
      });

      expect(token).toEqual({ text: "○", color: "#606060" });
    });
  });

  describe("selected row highlighting", () => {
    test("uses a subtle green row when selected model is not focused", () => {
      const color = selectedRowColor({
        themeId: "dark",
        isSelectedModel: true,
        isFocusedRow: false,
      });

      expect(color).toBe("#1f3a2f");
    });

    test("uses a brighter green row when selected model is focused", () => {
      const color = selectedRowColor({
        themeId: "dark",
        isSelectedModel: true,
        isFocusedRow: true,
      });

      expect(color).toBe("#2b4d3f");
    });
  });
});
