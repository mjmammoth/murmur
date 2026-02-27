/**
 * Convert a hex color string to an RGB triple.
 *
 * Supports `#rgb`, `#rrggbb`, and `#rrggbbaa` (alpha component is ignored).
 *
 * @param hex - The input hex color string (must start with `#`)
 * @returns A tuple `[r, g, b]` where each component is an integer in the range 0–255
 * @throws Error if the string does not start with `#`, if it isn't a supported length after `#` normalization, or if it contains non-hex characters
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

/**
 * Convert RGB component values to a 6-digit hex color string with a leading `#`.
 *
 * @param r - Red component (0–255)
 * @param g - Green component (0–255)
 * @param b - Blue component (0–255)
 * @returns A string in the format `#rrggbb`
 */
export function rgbToHex(r: number, g: number, b: number): string {
  const normalizeChannel = (value: number): number => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 0;
    return Math.max(0, Math.min(255, Math.round(numeric)));
  };

  const rr = normalizeChannel(r);
  const gg = normalizeChannel(g);
  const bb = normalizeChannel(b);
  return `#${((1 << 24) | (rr << 16) | (gg << 8) | bb).toString(16).slice(1)}`;
}

/**
 * Linearly interpolates between two hex color values.
 *
 * @param from - Starting color as a hex string (`#rgb`, `#rrggbb`, or `#rrggbbaa`)
 * @param to - Ending color as a hex string (`#rgb`, `#rrggbb`, or `#rrggbbaa`)
 * @param t - Interpolation factor in the range 0 to 1 where 0 yields `from` and 1 yields `to`
 * @returns A hex color string in the format `#rrggbb` representing the interpolated color
 */
export function lerpColor(from: string, to: string, t: number): string {
  const [r1, g1, b1] = hexToRgb(from);
  const [r2, g2, b2] = hexToRgb(to);
  return rgbToHex(
    Math.round(r1 + (r2 - r1) * t),
    Math.round(g1 + (g2 - g1) * t),
    Math.round(b1 + (b2 - b1) * t),
  );
}
