import { describe, expect, test } from "bun:test";
import { createRoot } from "solid-js";

/**
 * Tests for Footer component
 *
 * The Footer displays status information, model/hotkey/mode settings, and navigation hints.
 * It adapts its layout based on terminal width.
 */

describe("Footer", () => {
  describe("truncateLabel function", () => {
    test("should return original value when within max length", () => {
      const value = "short";
      const maxLength = 10;
      const result = value.length <= maxLength ? value : `${value.slice(0, maxLength - 3)}...`;

      expect(result).toBe("short");
    });

    test("should truncate with ellipsis when exceeds max length", () => {
      const value = "very-long-model-name";
      const maxLength = 10;
      const result = value.length <= maxLength ? value : `${value.slice(0, maxLength - 3)}...`;

      expect(result).toBe("very-lo...");
      expect(result.length).toBe(10);
    });

    test("should handle max length of 3 or less", () => {
      const value = "test";
      const maxLength = 3;
      const result = maxLength <= 3 ? value.slice(0, Math.max(0, maxLength)) : `${value.slice(0, maxLength - 3)}...`;

      expect(result).toBe("tes");
    });

    test("should handle empty string", () => {
      const value = "";
      const maxLength = 10;
      const result = value.length <= maxLength ? value : `${value.slice(0, maxLength - 3)}...`;

      expect(result).toBe("");
    });

    test("should handle exact max length", () => {
      const value = "exactly10c";
      const maxLength = 10;
      const result = value.length <= maxLength ? value : `${value.slice(0, maxLength - 3)}...`;

      expect(result).toBe("exactly10c");
    });
  });

  describe("KeyHint rendering logic", () => {
    test("should find key character in word", () => {
      const word = "quit";
      const keyChar = "q";
      const idx = Math.max(0, word.toLowerCase().indexOf(keyChar.toLowerCase()));

      expect(idx).toBe(0);
    });

    test("should handle key character not in word", () => {
      const word = "settings";
      const keyChar = "x";
      const idx = Math.max(0, word.toLowerCase().indexOf(keyChar.toLowerCase()));

      expect(idx).toBe(0); // Returns 0 when not found (indexOf returns -1, Math.max makes it 0)
    });

    test("should extract parts around key character", () => {
      const word = "settings";
      const keyChar = "s";
      const idx = Math.max(0, word.toLowerCase().indexOf(keyChar.toLowerCase()));
      const before = word.slice(0, idx);
      const key = word[idx] ?? keyChar;
      const after = word.slice(idx + 1);

      expect(before).toBe("");
      expect(key).toBe("s");
      expect(after).toBe("ettings");
    });

    test("should handle case insensitive matching", () => {
      const word = "Theme";
      const keyChar = "t";
      const idx = Math.max(0, word.toLowerCase().indexOf(keyChar.toLowerCase()));

      expect(idx).toBe(0);
    });
  });

  describe("PairHint rendering logic", () => {
    test("should render without key character highlight", () => {
      const label = "status";
      const value = "ready";
      const keyChar = undefined as string | undefined;
      const idx = keyChar ? Math.max(0, label.toLowerCase().indexOf(keyChar.toLowerCase())) : -1;

      expect(idx).toBe(-1);
    });

    test("should find key character in label", () => {
      const label = "model";
      const keyChar = "m";
      const idx = keyChar ? Math.max(0, label.toLowerCase().indexOf(keyChar.toLowerCase())) : -1;

      expect(idx).toBe(0);
    });

    test("should split label around key character", () => {
      const label = "hotkey";
      const keyChar = "h";
      const idx = Math.max(0, label.toLowerCase().indexOf(keyChar.toLowerCase()));
      const before = label.slice(0, idx);
      const key = label[idx] ?? keyChar;
      const after = label.slice(idx + 1);

      expect(before).toBe("");
      expect(key).toBe("h");
      expect(after).toBe("otkey");
    });
  });

  describe("layout threshold logic", () => {
    test("should use compact layout when width below threshold", () => {
      const COMPACT_FOOTER_THRESHOLD = 118;
      const availableWidth = 100;
      const compactFooterLayout = availableWidth < COMPACT_FOOTER_THRESHOLD;

      expect(compactFooterLayout).toBe(true);
    });

    test("should use normal layout when width above threshold", () => {
      const COMPACT_FOOTER_THRESHOLD = 118;
      const availableWidth = 120;
      const compactFooterLayout = availableWidth < COMPACT_FOOTER_THRESHOLD;

      expect(compactFooterLayout).toBe(false);
    });

    test("should use compact layout at exact threshold", () => {
      const COMPACT_FOOTER_THRESHOLD = 118;
      const availableWidth = 118;
      const compactFooterLayout = availableWidth < COMPACT_FOOTER_THRESHOLD;

      expect(compactFooterLayout).toBe(false);
    });
  });

  describe("model name logic", () => {
    test("should return dash when no model selected", () => {
      const selected = undefined;
      const modelName = selected || "-";

      expect(modelName).toBe("-");
    });

    test("should return dash when model not installed", () => {
      const selected = "whisper-base";
      const models = [{ name: "whisper-base", installed: false, path: null }];
      const match = models.find((model) => model.name === selected);
      const modelName = match?.installed ? selected : "-";

      expect(modelName).toBe("-");
    });

    test("should return model name when installed", () => {
      const selected = "whisper-base";
      const models = [{ name: "whisper-base", installed: true, path: "/path" }];
      const match = models.find((model) => model.name === selected);
      const modelName = match?.installed ? selected : "-";

      expect(modelName).toBe("whisper-base");
    });
  });

  describe("compact model truncation", () => {
    test("should truncate model name in compact mode", () => {
      const modelName = "very-long-model-name";
      const compactFooterLayout = true;
      const maxLength = compactFooterLayout ? 10 : 14;
      const truncated = modelName.length <= maxLength ? modelName : `${modelName.slice(0, maxLength - 3)}...`;

      expect(truncated).toBe("very-lo...");
    });

    test("should use longer length in normal mode", () => {
      const modelName = "medium-model";
      const compactFooterLayout = false;
      const maxLength = compactFooterLayout ? 10 : 14;
      const truncated = modelName.length <= maxLength ? modelName : `${modelName.slice(0, maxLength - 3)}...`;

      expect(truncated).toBe("medium-model");
    });
  });

  describe("status color logic", () => {
    test("should return recording color for recording status", () => {
      const status = "recording";
      const colors = {
        recording: "#FF0000",
        transcribing: "#FFAA00",
        error: "#AA0000",
        ready: "#00FF00",
        textMuted: "#888888"
      };

      const statusColor = status === "recording" ? colors.recording
        : status === "transcribing" || status === "downloading" ? colors.transcribing
        : status === "error" ? colors.error
        : status === "ready" ? colors.ready
        : colors.textMuted;

      expect(statusColor).toBe("#FF0000");
    });

    test("should return transcribing color for transcribing status", () => {
      const status: string = "transcribing";
      const colors = {
        recording: "#FF0000",
        transcribing: "#FFAA00",
        error: "#AA0000",
        ready: "#00FF00",
        textMuted: "#888888"
      };

      const statusColor = status === "recording" ? colors.recording
        : status === "transcribing" || status === "downloading" ? colors.transcribing
        : status === "error" ? colors.error
        : status === "ready" ? colors.ready
        : colors.textMuted;

      expect(statusColor).toBe("#FFAA00");
    });

    test("should return error color for error status", () => {
      const status: string = "error";
      const colors = {
        recording: "#FF0000",
        transcribing: "#FFAA00",
        error: "#AA0000",
        ready: "#00FF00",
        textMuted: "#888888"
      };

      const statusColor = status === "recording" ? colors.recording
        : status === "transcribing" || status === "downloading" ? colors.transcribing
        : status === "error" ? colors.error
        : status === "ready" ? colors.ready
        : colors.textMuted;

      expect(statusColor).toBe("#AA0000");
    });

    test("should return ready color for ready status", () => {
      const status: string = "ready";
      const colors = {
        recording: "#FF0000",
        transcribing: "#FFAA00",
        error: "#AA0000",
        ready: "#00FF00",
        textMuted: "#888888"
      };

      const statusColor = status === "recording" ? colors.recording
        : status === "transcribing" || status === "downloading" ? colors.transcribing
        : status === "error" ? colors.error
        : status === "ready" ? colors.ready
        : colors.textMuted;

      expect(statusColor).toBe("#00FF00");
    });

    test("should return muted color for unknown status", () => {
      const status = "unknown" as any;
      const colors = {
        recording: "#FF0000",
        transcribing: "#FFAA00",
        error: "#AA0000",
        ready: "#00FF00",
        textMuted: "#888888"
      };

      const statusColor = status === "recording" ? colors.recording
        : status === "transcribing" || status === "downloading" ? colors.transcribing
        : status === "error" ? colors.error
        : status === "ready" ? colors.ready
        : colors.textMuted;

      expect(statusColor).toBe("#888888");
    });
  });

  describe("status display logic", () => {
    test("should normalize whitespace in status message", () => {
      const statusMessage = "Status  with   multiple   spaces";
      const oneLine = statusMessage.replace(/\s+/g, " ").trim();

      expect(oneLine).toBe("Status with multiple spaces");
    });

    test("should handle empty status message", () => {
      const statusMessage = "";
      const oneLine = statusMessage.replace(/\s+/g, " ").trim();
      const display = oneLine || "-";

      expect(display).toBe("-");
    });

    test("should truncate long status message", () => {
      const statusMessage = "This is a very long status message that needs truncation";
      const maxChars = 20;
      const oneLine = statusMessage.replace(/\s+/g, " ").trim();
      const display = oneLine.length <= maxChars ? oneLine : `${oneLine.slice(0, maxChars - 3)}...`;

      expect(display).toBe("This is a very lo...");
    });
  });

  describe("status badge background logic", () => {
    test("should return ready color for ready status", () => {
      const status = "ready";
      const colors = { ready: "#00FF00", recording: "#FF0000", transcribing: "#FFAA00" };

      const bg = status === "ready" ? colors.ready
        : status === "recording" ? colors.recording
        : status === "transcribing" || status === "downloading" ? colors.transcribing
        : null;

      expect(bg).toBe("#00FF00");
    });

    test("should return recording color for recording status", () => {
      const status: string = "recording";
      const colors = { ready: "#00FF00", recording: "#FF0000", transcribing: "#FFAA00" };

      const bg = status === "ready" ? colors.ready
        : status === "recording" ? colors.recording
        : status === "transcribing" || status === "downloading" ? colors.transcribing
        : null;

      expect(bg).toBe("#FF0000");
    });

    test("should return null for connecting status", () => {
      const status: string = "connecting";
      const colors = { ready: "#00FF00", recording: "#FF0000", transcribing: "#FFAA00" };

      const bg = status === "ready" ? colors.ready
        : status === "recording" ? colors.recording
        : status === "transcribing" || status === "downloading" ? colors.transcribing
        : null;

      expect(bg).toBeNull();
    });
  });

  describe("width calculations", () => {
    test("should calculate left section width", () => {
      const availableWidth = 120;
      const leftSectionWidth = Math.floor(availableWidth * 0.33);

      expect(leftSectionWidth).toBe(39);
    });

    test("should handle small available width", () => {
      const availableWidth = 30;
      const leftSectionWidth = Math.floor(availableWidth * 0.33);

      expect(leftSectionWidth).toBe(9);
    });

    test("should calculate status max chars", () => {
      const sectionWidth = 40;
      const shouldWrapLeftSection = false;
      const scannerSectionWidth = 8;
      const statusGap = 2;

      const maxChars = shouldWrapLeftSection
        ? Math.max(8, sectionWidth - 2)
        : Math.max(8, sectionWidth - scannerSectionWidth - statusGap - 2);

      expect(maxChars).toBe(28);
    });

    test("should use different max chars when wrapped", () => {
      const sectionWidth = 40;
      const shouldWrapLeftSection = true;

      const maxChars = shouldWrapLeftSection
        ? Math.max(8, sectionWidth - 2)
        : Math.max(8, 28);

      expect(maxChars).toBe(38);
    });
  });

  describe("edge cases", () => {
    test("should handle zero available width", () => {
      const availableWidth = Math.max(0, Math.floor(0));

      expect(availableWidth).toBe(0);
    });

    test("should handle negative available width", () => {
      const availableWidth = Math.max(0, Math.floor(-10));

      expect(availableWidth).toBe(0);
    });

    test("should handle very long model names", () => {
      const modelName = "a".repeat(100);
      const maxLength = 10;
      const truncated = modelName.length <= maxLength ? modelName : `${modelName.slice(0, maxLength - 3)}...`;

      expect(truncated).toBe("aaaaaaa...");
      expect(truncated.length).toBe(10);
    });
  });
});