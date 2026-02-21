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
 * Truncate text to a maximum length with ellipsis.
 */
export function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) {
    return text;
  }
  return text.slice(0, maxLength - 3) + "...";
}

/**
 * Format model runtime device names for user-facing UI labels.
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
