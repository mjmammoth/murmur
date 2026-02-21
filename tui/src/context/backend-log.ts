import type { LogEntry } from "../types";

const MAX_LOG_ENTRIES = 200;

export function appendLogWithLimit(prev: LogEntry[], entry: LogEntry): LogEntry[] {
  const next = [...prev, entry];
  return next.length > MAX_LOG_ENTRIES ? next.slice(-MAX_LOG_ENTRIES) : next;
}

export function formatClientLogTimestamp(now: Date = new Date()): string {
  return now.toTimeString().slice(0, 8);
}
