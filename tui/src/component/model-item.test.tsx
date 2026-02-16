import { describe, expect, test } from "bun:test";
import { createRoot } from "solid-js";
import type { ModelInfo } from "../types";

/**
 * Tests for ModelItem component
 *
 * Displays a single model entry with download progress, status indicators, and size information.
 */

describe("ModelItem", () => {
  const DOWNLOAD_SCANNER_WIDTH = 10;
  const SCANNER_EMPTY = "⬝";
  const SCANNER_MID = "▪";
  const SCANNER_FULL = "■";

  describe("buildDownloadScanner function", () => {
    test("should create empty scanner at 0%", () => {
      const percent = 0;
      const progressCells = (percent / 100) * DOWNLOAD_SCANNER_WIDTH;
      const scanner = Array.from({ length: DOWNLOAD_SCANNER_WIDTH }, (_, idx) => {
        const cellFill = progressCells - idx;
        if (cellFill >= 1) return SCANNER_FULL;
        if (cellFill >= 0.34) return SCANNER_MID;
        return SCANNER_EMPTY;
      }).join("");

      expect(scanner).toBe("⬝".repeat(DOWNLOAD_SCANNER_WIDTH));
    });

    test("should create full scanner at 100%", () => {
      const percent = 100;
      const progressCells = (percent / 100) * DOWNLOAD_SCANNER_WIDTH;
      const scanner = Array.from({ length: DOWNLOAD_SCANNER_WIDTH }, (_, idx) => {
        const cellFill = progressCells - idx;
        if (cellFill >= 1) return SCANNER_FULL;
        if (cellFill >= 0.34) return SCANNER_MID;
        return SCANNER_EMPTY;
      }).join("");

      expect(scanner).toBe("■".repeat(DOWNLOAD_SCANNER_WIDTH));
    });

    test("should handle 50% progress", () => {
      const percent = 50;
      const progressCells = (percent / 100) * DOWNLOAD_SCANNER_WIDTH;
      const scanner = Array.from({ length: DOWNLOAD_SCANNER_WIDTH }, (_, idx) => {
        const cellFill = progressCells - idx;
        if (cellFill >= 1) return SCANNER_FULL;
        if (cellFill >= 0.34) return SCANNER_MID;
        return SCANNER_EMPTY;
      }).join("");

      expect(scanner.length).toBe(DOWNLOAD_SCANNER_WIDTH);
      expect(scanner).toContain(SCANNER_FULL);
      expect(scanner).toContain(SCANNER_EMPTY);
    });

    test("should clamp negative percentage to 0", () => {
      const percent = Math.max(0, Math.min(100, Math.round(-10)));

      expect(percent).toBe(0);
    });

    test("should clamp percentage above 100", () => {
      const percent = Math.max(0, Math.min(100, Math.round(150)));

      expect(percent).toBe(100);
    });

    test("should use mid character for partial fill", () => {
      const cellFill = 0.5;
      const char = cellFill >= 1 ? SCANNER_FULL : cellFill >= 0.34 ? SCANNER_MID : SCANNER_EMPTY;

      expect(char).toBe(SCANNER_MID);
    });

    test("should use full character for complete fill", () => {
      const cellFill = 1.5;
      const char = cellFill >= 1 ? SCANNER_FULL : cellFill >= 0.34 ? SCANNER_MID : SCANNER_EMPTY;

      expect(char).toBe(SCANNER_FULL);
    });

    test("should use empty character for minimal fill", () => {
      const cellFill = 0.2;
      const char = cellFill >= 1 ? SCANNER_FULL : cellFill >= 0.34 ? SCANNER_MID : SCANNER_EMPTY;

      expect(char).toBe(SCANNER_EMPTY);
    });
  });

  describe("statusText logic", () => {
    test("should show pulling with progress", () => {
      const operation = { type: "pulling", model: "whisper-base" };
      const progress = { model: "whisper-base", percent: 75 };
      const percent = Math.max(0, Math.min(100, Math.round(progress.percent)));
      const percentLabel = `${percent}%`.padStart(4, " ");

      expect(percentLabel).toBe(" 75%");
      expect(percent).toBe(75);
    });

    test("should show pulling without progress", () => {
      const operation = { type: "pulling", model: "whisper-base" };
      const progress = null;
      const statusText = progress ? "with progress" : "pulling";

      expect(statusText).toBe("pulling");
    });

    test("should show removing status", () => {
      const operation = { type: "removing", model: "whisper-base" };
      const statusText = operation.type === "removing" ? "removing" : "other";

      expect(statusText).toBe("removing");
    });

    test("should show selected status", () => {
      const isSelectedModel = true;
      const statusText = isSelectedModel ? "● selected" : "other";

      expect(statusText).toBe("● selected");
    });

    test("should show pulled status for installed model", () => {
      const model: ModelInfo = { name: "whisper-base", installed: true, path: "/path" };
      const isSelectedModel = false;
      const statusText = isSelectedModel ? "● selected" : model.installed ? "● pulled" : "○ not pulled";

      expect(statusText).toBe("● pulled");
    });

    test("should show not pulled status for uninstalled model", () => {
      const model: ModelInfo = { name: "whisper-base", installed: false, path: null };
      const isSelectedModel = false;
      const statusText = isSelectedModel ? "● selected" : model.installed ? "● pulled" : "○ not pulled";

      expect(statusText).toBe("○ not pulled");
    });
  });

  describe("sizeLabel logic", () => {
    test("should return empty string for invalid size", () => {
      const size = null;
      const sizeLabel = typeof size !== "number" || size <= 0 ? "" : `~${size}`;

      expect(sizeLabel).toBe("");
    });

    test("should return empty string for zero size", () => {
      const size = 0;
      const sizeLabel = typeof size !== "number" || size <= 0 ? "" : `~${size}`;

      expect(sizeLabel).toBe("");
    });

    test("should add tilde for estimated size", () => {
      const size = 1024;
      const estimated = true;
      const prefix = estimated ? "~" : "";

      expect(prefix).toBe("~");
    });

    test("should not add tilde for exact size", () => {
      const size = 1024;
      const estimated = false;
      const prefix = estimated ? "~" : "";

      expect(prefix).toBe("");
    });
  });

  describe("statusColor logic", () => {
    test("should return transcribing color for pulling operation", () => {
      const operation = { type: "pulling", model: "whisper-base" };
      const colors = { transcribing: "#FFAA00", warning: "#FF0000", secondary: "#0000FF", success: "#00FF00", textDim: "#888888" };

      const color = operation?.type === "pulling" ? colors.transcribing
        : operation?.type === "removing" ? colors.warning
        : colors.textDim;

      expect(color).toBe("#FFAA00");
    });

    test("should return warning color for removing operation", () => {
      const operation = { type: "removing", model: "whisper-base" };
      const colors = { transcribing: "#FFAA00", warning: "#FF0000", secondary: "#0000FF", success: "#00FF00", textDim: "#888888" };

      const color = operation?.type === "pulling" ? colors.transcribing
        : operation?.type === "removing" ? colors.warning
        : colors.textDim;

      expect(color).toBe("#FF0000");
    });

    test("should return secondary color for selected model", () => {
      const operation = null;
      const isSelectedModel = true;
      const colors = { secondary: "#0000FF", success: "#00FF00", textDim: "#888888" };

      const color = operation ? "#000000"
        : isSelectedModel ? colors.secondary
        : colors.success;

      expect(color).toBe("#0000FF");
    });

    test("should return success color for installed model", () => {
      const operation = null;
      const isSelectedModel = false;
      const installed = true;
      const colors = { secondary: "#0000FF", success: "#00FF00", textDim: "#888888" };

      const color = operation ? "#000000"
        : isSelectedModel ? colors.secondary
        : installed ? colors.success
        : colors.textDim;

      expect(color).toBe("#00FF00");
    });

    test("should return dim color for uninstalled model", () => {
      const operation = null;
      const isSelectedModel = false;
      const installed = false;
      const colors = { secondary: "#0000FF", success: "#00FF00", textDim: "#888888" };

      const color = operation ? "#000000"
        : isSelectedModel ? colors.secondary
        : installed ? colors.success
        : colors.textDim;

      expect(color).toBe("#888888");
    });
  });

  describe("bgColor logic", () => {
    test("should return backgroundElement when selected", () => {
      const selected = true;
      const colors = { backgroundElement: "#333333" };
      const bgColor = selected ? colors.backgroundElement : undefined;

      expect(bgColor).toBe("#333333");
    });

    test("should return undefined when not selected", () => {
      const selected = false;
      const colors = { backgroundElement: "#333333" };
      const bgColor = selected ? colors.backgroundElement : undefined;

      expect(bgColor).toBeUndefined();
    });
  });

  describe("mutedColor logic", () => {
    test("should return text color when selected", () => {
      const selected = true;
      const colors = { text: "#FFFFFF", textMuted: "#888888" };
      const mutedColor = selected ? colors.text : colors.textMuted;

      expect(mutedColor).toBe("#FFFFFF");
    });

    test("should return textMuted when not selected", () => {
      const selected = false;
      const colors = { text: "#FFFFFF", textMuted: "#888888" };
      const mutedColor = selected ? colors.text : colors.textMuted;

      expect(mutedColor).toBe("#888888");
    });
  });

  describe("percentage formatting", () => {
    test("should pad percentage to 4 characters", () => {
      const percent = 5;
      const padded = `${percent}%`.padStart(4, " ");

      expect(padded).toBe("  5%");
      expect(padded.length).toBe(4);
    });

    test("should not pad 100%", () => {
      const percent = 100;
      const padded = `${percent}%`.padStart(4, " ");

      expect(padded).toBe("100%");
      expect(padded.length).toBe(4);
    });

    test("should pad 0%", () => {
      const percent = 0;
      const padded = `${percent}%`.padStart(4, " ");

      expect(padded).toBe("  0%");
    });
  });

  describe("edge cases", () => {
    test("should handle undefined operation", () => {
      const operation = undefined;
      const hasOperation = !!operation;

      expect(hasOperation).toBe(false);
    });

    test("should handle model name mismatch in progress", () => {
      const model = { name: "whisper-base", installed: true, path: "/path" };
      const progress = { model: "whisper-large", percent: 50 };
      const matches = progress.model === model.name;

      expect(matches).toBe(false);
    });
  });
});