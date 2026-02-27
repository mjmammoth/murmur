export interface ToastMeta {
  log?: boolean;
  source?: string;
  dedupeKey?: string;
}

export const TOAST_LOG_DEDUPE_WINDOW_MS = 1500;

/**
 * Builds a deduplication key for toast logs.
 *
 * @param level - Log level, either `"info"` or `"error"`
 * @param message - The toast message text used when no dedupe key is provided
 * @param meta - Optional toast metadata; `meta.dedupeKey` overrides `message` for deduplication, and `meta.source` identifies the origin (defaults to `ui.toast`)
 * @returns A string key formed from the level, the dedupe identifier (either `meta.dedupeKey` or `message`), and the source, separated by `|`
 */
export function toastLogDedupeKey(level: "info" | "error", message: string, meta?: ToastMeta): string {
  const source = meta?.source ?? "ui.toast";
  return `${level}|${meta?.dedupeKey ?? message}|${source}`;
}

/**
 * Determines whether a toast log should be emitted based on a per-key time-based dedupe cache.
 *
 * @param dedupeCache - Map storing the last emitted timestamp (ms) for each dedupe key; will be updated when a log is allowed
 * @param key - The dedupe key identifying the toast message
 * @param now - Current timestamp in milliseconds
 * @param windowMs - Time window in milliseconds during which repeated logs for the same key are suppressed (defaults to TOAST_LOG_DEDUPE_WINDOW_MS)
 * @returns `true` if the log should be emitted (and the cache updated with `now`), `false` if the log is suppressed because it occurred within the window
 */
export function shouldMirrorToastLog(
  dedupeCache: Map<string, number>,
  key: string,
  now: number,
  windowMs: number = TOAST_LOG_DEDUPE_WINDOW_MS,
): boolean {
  for (const [cachedKey, timestamp] of dedupeCache) {
    if (now - timestamp > windowMs) {
      dedupeCache.delete(cachedKey);
    }
  }

  const lastLoggedAt = dedupeCache.get(key);
  if (lastLoggedAt !== undefined && now - lastLoggedAt < windowMs) {
    return false;
  }
  dedupeCache.set(key, now);
  return true;
}

/**
 * Determine whether a toast should be logged based on provided metadata.
 *
 * @param meta - Optional toast metadata; if present, `meta.log === false` disables logging
 * @returns `true` if the toast should be logged (i.e., `meta.log` is not `false`), `false` otherwise
 */
export function shouldLogToast(meta?: ToastMeta): boolean {
  return meta?.log !== false;
}
