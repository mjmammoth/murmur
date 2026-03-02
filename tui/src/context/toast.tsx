import { createSignal, onCleanup, onMount, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";
import { useBackend } from "./backend";
import type { Toast } from "../types";
import {
  shouldLogToast,
  shouldMirrorToastLog,
  toastLogDedupeKey,
  TOAST_LOG_DEDUPE_WINDOW_MS,
  type ToastMeta,
} from "./toast-log";

export interface ToastContextValue {
  toasts: Accessor<Toast[]>;
  showToast: (message: string, meta?: ToastMeta) => void;
  showError: (message: string, meta?: ToastMeta) => void;
}

const [ToastProvider, useToast] = createContextHelper<ToastContextValue>("Toast");
export { useToast };

const TOAST_DURATION = 4000;

/**
 * Creates and returns a ToastProvider that supplies toast state and controls to its children.
 *
 * The provider exposes `toasts`, `showToast(message, meta?)`, and `showError(message, meta?)`.
 * Toasts auto-dismiss after a fixed duration, may be mirrored to the backend based on metadata,
 * and backend-originated toasts are received and displayed without re-logging.
 *
 * @param props.children - The element subtree that will receive the toast context
 * @returns The ToastProvider element that wraps `props.children` and provides toast state and APIs
 */
export function ToastContextProvider(props: { children: JSX.Element }): JSX.Element {
  const backend = useBackend();

  const [toasts, setToasts] = createSignal<Toast[]>([]);
  let nextId = 0;
  const lastLogAtByKey = new Map<string, number>();
  const dismissTimers = new Map<number, ReturnType<typeof setTimeout>>();

  function scheduleDismiss(id: number) {
    const timer = setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
      dismissTimers.delete(id);
    }, TOAST_DURATION);
    dismissTimers.set(id, timer);
  }

  function addToast(message: string, level: "info" | "error", meta?: ToastMeta) {
    const id = nextId++;
    setToasts((prev) => [...prev, { id, message, level }]);

    if (shouldLogToast(meta)) {
      const source = meta?.source ?? "ui.toast";
      const now = Date.now();
      const staleCutoff = now - TOAST_LOG_DEDUPE_WINDOW_MS;
      for (const [cacheKey, lastAt] of lastLogAtByKey) {
        if (lastAt < staleCutoff) {
          lastLogAtByKey.delete(cacheKey);
        }
      }
      const key = toastLogDedupeKey(level, message, { ...meta, source });
      if (shouldMirrorToastLog(lastLogAtByKey, key, now)) {
        backend.appendClientLog({
          level: level === "error" ? "ERROR" : "INFO",
          message,
          source,
        });
      }
    }

    scheduleDismiss(id);
  }

  function showToast(message: string, meta?: ToastMeta) {
    addToast(message, "info", meta);
  }

  function showError(message: string, meta?: ToastMeta) {
    addToast(message, "error", meta);
  }

  // Listen for toast messages from backend
  onMount(() => {
    const disposeToast = backend.onToast((message, level) => {
      addToast(message, level, { log: false, source: "backend.toast" });
    });
    onCleanup(() => {
      disposeToast();
      for (const timer of dismissTimers.values()) {
        clearTimeout(timer);
      }
      dismissTimers.clear();
    });
  });

  const value: ToastContextValue = {
    toasts,
    showToast,
    showError,
  };

  return <ToastProvider value={value}>{props.children}</ToastProvider>;
}
