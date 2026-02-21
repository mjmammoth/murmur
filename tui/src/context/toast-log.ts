export interface ToastMeta {
  log?: boolean;
  source?: string;
  dedupeKey?: string;
}

export const TOAST_LOG_DEDUPE_WINDOW_MS = 1500;

export function toastLogDedupeKey(level: "info" | "error", message: string, meta?: ToastMeta): string {
  const source = meta?.source ?? "ui.toast";
  return `${level}|${meta?.dedupeKey ?? message}|${source}`;
}

export function shouldMirrorToastLog(
  dedupeCache: Map<string, number>,
  key: string,
  now: number,
  windowMs: number = TOAST_LOG_DEDUPE_WINDOW_MS,
): boolean {
  const lastLoggedAt = dedupeCache.get(key);
  if (lastLoggedAt !== undefined && now - lastLoggedAt < windowMs) {
    return false;
  }
  dedupeCache.set(key, now);
  return true;
}

export function shouldLogToast(meta?: ToastMeta): boolean {
  return meta?.log !== false;
}
