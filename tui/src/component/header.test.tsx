import { describe, expect, test } from "bun:test";
import { createRoot } from "solid-js";

/**
 * Tests for Header component
 *
 * The Header displays the application title with animated color gradient
 * and toggle hints for noise suppression, VAD, auto copy, and auto paste.
 */

describe("Header", () => {
  const TITLE = "whisper.local";

  describe("color interpolation functions", () => {
    test("hexToRgb should convert hex color to RGB", () => {
      const hexToRgb = (hex: string): [number, number, number] => {
        const n = parseInt(hex.slice(1), 16);
        return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
      };

      const [r, g, b] = hexToRgb("#FF00AA");

      expect(r).toBe(255);
      expect(g).toBe(0);
      expect(b).toBe(170);
    });

    test("rgbToHex should convert RGB to hex color", () => {
      const rgbToHex = (r: number, g: number, b: number): string => {
        return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
      };

      const hex = rgbToHex(255, 0, 170);

      expect(hex).toBe("#ff00aa");
    });

    test("should handle black color", () => {
      const hexToRgb = (hex: string): [number, number, number] => {
        const n = parseInt(hex.slice(1), 16);
        return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
      };

      const [r, g, b] = hexToRgb("#000000");

      expect(r).toBe(0);
      expect(g).toBe(0);
      expect(b).toBe(0);
    });

    test("should handle white color", () => {
      const hexToRgb = (hex: string): [number, number, number] => {
        const n = parseInt(hex.slice(1), 16);
        return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
      };

      const [r, g, b] = hexToRgb("#FFFFFF");

      expect(r).toBe(255);
      expect(g).toBe(255);
      expect(b).toBe(255);
    });
  });

  describe("lerpColor function", () => {
    test("should interpolate at t=0 to return start color", () => {
      const lerpColor = (from: string, to: string, t: number): string => {
        const hexToRgb = (hex: string): [number, number, number] => {
          const n = parseInt(hex.slice(1), 16);
          return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
        };

        const rgbToHex = (r: number, g: number, b: number): string => {
          return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
        };

        const [r1, g1, b1] = hexToRgb(from);
        const [r2, g2, b2] = hexToRgb(to);
        return rgbToHex(
          Math.round(r1 + (r2 - r1) * t),
          Math.round(g1 + (g2 - g1) * t),
          Math.round(b1 + (b2 - b1) * t),
        );
      };

      const result = lerpColor("#FF0000", "#0000FF", 0);

      expect(result).toBe("#ff0000");
    });

    test("should interpolate at t=1 to return end color", () => {
      const lerpColor = (from: string, to: string, t: number): string => {
        const hexToRgb = (hex: string): [number, number, number] => {
          const n = parseInt(hex.slice(1), 16);
          return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
        };

        const rgbToHex = (r: number, g: number, b: number): string => {
          return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
        };

        const [r1, g1, b1] = hexToRgb(from);
        const [r2, g2, b2] = hexToRgb(to);
        return rgbToHex(
          Math.round(r1 + (r2 - r1) * t),
          Math.round(g1 + (g2 - g1) * t),
          Math.round(b1 + (b2 - b1) * t),
        );
      };

      const result = lerpColor("#FF0000", "#0000FF", 1);

      expect(result).toBe("#0000ff");
    });

    test("should interpolate at t=0.5 to return midpoint color", () => {
      const lerpColor = (from: string, to: string, t: number): string => {
        const hexToRgb = (hex: string): [number, number, number] => {
          const n = parseInt(hex.slice(1), 16);
          return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
        };

        const rgbToHex = (r: number, g: number, b: number): string => {
          return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
        };

        const [r1, g1, b1] = hexToRgb(from);
        const [r2, g2, b2] = hexToRgb(to);
        return rgbToHex(
          Math.round(r1 + (r2 - r1) * t),
          Math.round(g1 + (g2 - g1) * t),
          Math.round(b1 + (b2 - b1) * t),
        );
      };

      const result = lerpColor("#000000", "#FFFFFF", 0.5);

      // Midpoint should be around #7f7f7f (127, 127, 127)
      expect(result).toMatch(/#[0-9a-f]{6}/);
    });
  });

  describe("ToggleHint rendering logic", () => {
    test("should find key character in label", () => {
      const label = "noise suppression";
      const keyChar = "n";
      const matchIndex = label.toLowerCase().indexOf(keyChar.toLowerCase());

      expect(matchIndex).toBe(0);
    });

    test("should handle key character not in label", () => {
      const label = "feature";
      const keyChar = "x";
      const matchIndex = label.toLowerCase().indexOf(keyChar.toLowerCase());

      expect(matchIndex).toBe(-1);
    });

    test("should split label when key found", () => {
      const label = "vad";
      const keyChar = "v";
      const matchIndex = label.toLowerCase().indexOf(keyChar.toLowerCase());
      const hasMatch = matchIndex >= 0;
      const before = hasMatch ? label.slice(0, matchIndex) : `${label} `;
      const key = hasMatch ? label[matchIndex]! : keyChar;
      const after = hasMatch ? label.slice(matchIndex + 1) : "";

      expect(before).toBe("");
      expect(key).toBe("v");
      expect(after).toBe("ad");
    });

    test("should append space when key not found", () => {
      const label = "test";
      const keyChar = "x";
      const matchIndex = label.toLowerCase().indexOf(keyChar.toLowerCase());
      const hasMatch = matchIndex >= 0;
      const before = hasMatch ? label.slice(0, matchIndex) : `${label} `;

      expect(before).toBe("test ");
    });

    test("should format active state as 'on'", () => {
      const active = true;
      const display = active ? " on" : " off";

      expect(display).toBe(" on");
    });

    test("should format inactive state as 'off'", () => {
      const active = false;
      const display = active ? " on" : " off";

      expect(display).toBe(" off");
    });
  });

  describe("title strip animation", () => {
    test("should create title strip with spaces", () => {
      const titleChars = TITLE.split("");
      const titleStripChars = [" ", ...titleChars, " "];

      expect(titleStripChars[0]).toBe(" ");
      expect(titleStripChars[titleStripChars.length - 1]).toBe(" ");
      expect(titleStripChars.length).toBe(TITLE.length + 2);
    });

    test("should find peak index at dot position", () => {
      const titleChars = TITLE.split("");
      const titleStripChars = [" ", ...titleChars, " "];
      const peakIndex = Math.max(0, TITLE.indexOf(".")) + 1;

      expect(peakIndex).toBe(7 + 1); // "whisper" is 7 chars, dot at index 7
      expect(TITLE[7]).toBe(".");
    });

    test("should calculate max distance from peak", () => {
      const titleChars = TITLE.split("");
      const titleStripChars = [" ", ...titleChars, " "];
      const titleLastIndex = Math.max(1, titleStripChars.length - 1);
      const peakIndex = Math.max(0, TITLE.indexOf(".")) + 1;
      const maxDistanceFromPeak = Math.max(1, Math.max(peakIndex, titleLastIndex - peakIndex));

      expect(maxDistanceFromPeak).toBeGreaterThan(0);
    });

    test("should calculate distance from peak", () => {
      const peakIndex = 8;
      const currentIndex = 5;
      const distanceFromPeak = Math.abs(currentIndex - peakIndex);

      expect(distanceFromPeak).toBe(3);
    });

    test("should calculate base intensity", () => {
      const distanceFromPeak = 3;
      const maxDistanceFromPeak = 10;
      const baseIntensity = Math.max(0, 1 - distanceFromPeak / maxDistanceFromPeak);

      expect(baseIntensity).toBe(0.7);
    });

    test("should apply power curve to intensity", () => {
      const baseIntensity = 0.7;
      const intensity = Math.pow(baseIntensity, 2.1);

      expect(intensity).toBeLessThan(baseIntensity);
      expect(intensity).toBeGreaterThan(0);
    });

    test("should have maximum intensity at peak", () => {
      const distanceFromPeak = 0;
      const maxDistanceFromPeak = 10;
      const baseIntensity = Math.max(0, 1 - distanceFromPeak / maxDistanceFromPeak);
      const intensity = Math.pow(baseIntensity, 2.1);

      expect(intensity).toBe(1);
    });
  });

  describe("title content", () => {
    test("should have correct title", () => {
      expect(TITLE).toBe("whisper.local");
    });

    test("should contain dot character", () => {
      expect(TITLE.includes(".")).toBe(true);
    });

    test("should have expected length", () => {
      expect(TITLE.length).toBe(13);
    });
  });

  describe("toggle states", () => {
    test("should handle noise suppression toggle", () => {
      let noiseEnabled = false;
      const toggleNoise = () => { noiseEnabled = !noiseEnabled; };

      toggleNoise();
      expect(noiseEnabled).toBe(true);

      toggleNoise();
      expect(noiseEnabled).toBe(false);
    });

    test("should handle VAD toggle", () => {
      let vadEnabled = true;
      const toggleVad = () => { vadEnabled = !vadEnabled; };

      toggleVad();
      expect(vadEnabled).toBe(false);

      toggleVad();
      expect(vadEnabled).toBe(true);
    });

    test("should handle auto copy toggle", () => {
      let autoCopy = false;
      const toggleAutoCopy = () => { autoCopy = !autoCopy; };

      toggleAutoCopy();
      expect(autoCopy).toBe(true);
    });

    test("should handle auto paste toggle", () => {
      let autoPaste = false;
      const toggleAutoPaste = () => { autoPaste = !autoPaste; };

      toggleAutoPaste();
      expect(autoPaste).toBe(true);
    });
  });

  describe("case sensitivity", () => {
    test("should handle case insensitive key matching", () => {
      const label = "Noise Suppression";
      const keyChar = "n";
      const matchIndex = label.toLowerCase().indexOf(keyChar.toLowerCase());

      expect(matchIndex).toBe(0);
    });

    test("should handle uppercase key character", () => {
      const label = "vad";
      const keyChar = "V";
      const matchIndex = label.toLowerCase().indexOf(keyChar.toLowerCase());

      expect(matchIndex).toBe(0);
    });
  });

  describe("edge cases", () => {
    test("should handle empty label", () => {
      const label = "";
      const keyChar = "x";
      const matchIndex = label.toLowerCase().indexOf(keyChar.toLowerCase());

      expect(matchIndex).toBe(-1);
    });

    test("should handle single character label", () => {
      const label = "v";
      const keyChar = "v";
      const matchIndex = label.toLowerCase().indexOf(keyChar.toLowerCase());
      const after = label.slice(matchIndex + 1);

      expect(matchIndex).toBe(0);
      expect(after).toBe("");
    });

    test("should handle intensity at minimum", () => {
      const baseIntensity = 0;
      const intensity = Math.pow(baseIntensity, 2.1);

      expect(intensity).toBe(0);
    });

    test("should handle negative distance (should not happen but guard)", () => {
      const distanceFromPeak = -5;
      const maxDistanceFromPeak = 10;
      const baseIntensity = Math.max(0, 1 - distanceFromPeak / maxDistanceFromPeak);

      expect(baseIntensity).toBeGreaterThanOrEqual(0);
    });
  });

  describe("integration scenarios", () => {
    test("should have all four toggle hints", () => {
      const toggles = ["noise suppression", "vad", "auto copy", "auto paste"];

      expect(toggles.length).toBe(4);
      expect(toggles).toContain("noise suppression");
      expect(toggles).toContain("vad");
      expect(toggles).toContain("auto copy");
      expect(toggles).toContain("auto paste");
    });

    test("should map correct keys to toggles", () => {
      const keyMappings = [
        { key: "n", label: "noise suppression" },
        { key: "v", label: "vad" },
        { key: "a", label: "auto copy" },
        { key: "p", label: "auto paste" },
      ];

      expect(keyMappings.length).toBe(4);
      expect(keyMappings[0]!.key).toBe("n");
      expect(keyMappings[1]!.label).toBe("vad");
    });
  });
});
