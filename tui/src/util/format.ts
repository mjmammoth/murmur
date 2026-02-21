/**
 * Format bytes to human readable string (B, KB, MB, GB).
 */
export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex++;
  }

  const unit = units[unitIndex];
  if (unit === "B") {
    return `${Math.round(value)} ${unit}`;
  }
  return `${value.toFixed(1)} ${unit}`;
}

/**
 * Format elapsed time in seconds.
 */
export function formatElapsed(seconds: number): string {
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes}m ${secs}s`;
}

/**
 * Shortens a string to a maximum length, appending an ellipsis when truncated.
 *
 * If truncation is necessary, the result is the first `maxLength - 3` characters of `text` followed by `"..."`.
 *
 * @param text - The input string to truncate
 * @param maxLength - The maximum allowed length of the returned string, including the ellipsis when present
 * @returns The original `text` when its length is less than or equal to `maxLength`, otherwise a truncated string ending with `"..."`
 */
export function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) {
    return text;
  }
  return text.slice(0, maxLength - 3) + "...";
}

/**
 * Format a model runtime device name for display in the UI.
 *
 * Converts null or empty input to the provided fallback, normalizes common
 * device identifiers to user-friendly labels, and otherwise returns the
 * trimmed original text.
 *
 * @param value - Device identifier (may be `null` or `undefined`)
 * @param fallback - Value to return when `value` is null, undefined, or empty
 * @returns The user-facing device label (e.g., `"CPU"`, `"CUDA"`, `"Metal (mps)"`, or the original text)
 */
export function formatDeviceLabel(value: string | null | undefined, fallback = "-"): string {
  if (value === null || value === undefined) return fallback;

  const text = String(value).trim();
  if (!text) return fallback;

  const normalized = text.toLowerCase();
  if (normalized === "cpu") return "CPU";
  if (normalized === "cuda") return "CUDA";
  if (normalized === "mps") return "Metal (mps)";

  return text;
}