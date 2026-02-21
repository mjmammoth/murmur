/**
 * Convert hex colors to RGB.
 * Supports #rgb, #rrggbb, and #rrggbbaa (alpha ignored).
 */
export function hexToRgb(hex: string): [number, number, number] {
  if (!hex.startsWith("#")) {
    throw new Error(`Invalid hex color "${hex}": missing leading "#".`);
  }

  let normalized = hex.slice(1);
  if (normalized.length === 3) {
    normalized = normalized
      .split("")
      .map((channel) => `${channel}${channel}`)
      .join("");
  } else if (normalized.length === 8) {
    normalized = normalized.slice(0, 6);
  } else if (normalized.length !== 6) {
    throw new Error(
      `Invalid hex color "${hex}": expected #rgb, #rrggbb, or #rrggbbaa.`,
    );
  }

  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
    throw new Error(`Invalid hex color "${hex}": contains non-hex characters.`);
  }

  const n = Number.parseInt(normalized, 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

export function rgbToHex(r: number, g: number, b: number): string {
  return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
}

export function lerpColor(from: string, to: string, t: number): string {
  const [r1, g1, b1] = hexToRgb(from);
  const [r2, g2, b2] = hexToRgb(to);
  return rgbToHex(
    Math.round(r1 + (r2 - r1) * t),
    Math.round(g1 + (g2 - g1) * t),
    Math.round(b1 + (b2 - b1) * t),
  );
}
