import type { LogEntry } from "../types";

const MAX_LOG_ENTRIES = 200;

/**
 * Appends a log entry to an existing array and enforces the maximum retained entries.
 *
 * @param prev - Existing array of log entries
 * @param entry - Log entry to append
 * @returns A new array with `entry` appended, truncated to the last 200 entries if the limit is exceeded
 */
export function appendLogWithLimit(prev: LogEntry[], entry: LogEntry): LogEntry[] {
  const next = [...prev, entry];
  return next.length > MAX_LOG_ENTRIES ? next.slice(-MAX_LOG_ENTRIES) : next;
}

/**
 * Produce an HH:MM:SS timestamp string from the given Date.
 *
 * @param now - Date to format; defaults to the current date/time.
 * @returns The time portion formatted as `HH:MM:SS`.
 */
export function formatClientLogTimestamp(now: Date = new Date()): string {
  return now.toTimeString().slice(0, 8);
}
