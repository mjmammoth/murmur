import { createSignal, onMount, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";
import { useBackend } from "./backend";
import type { Toast } from "../types";

export interface ToastContextValue {
  toasts: Accessor<Toast[]>;
  showToast: (message: string) => void;
  showError: (message: string) => void;
}

const [ToastProvider, useToast] = createContextHelper<ToastContextValue>("Toast");
export { useToast };

const TOAST_DURATION = 2500;

export function ToastContextProvider(props: { children: JSX.Element }): JSX.Element {
  const backend = useBackend();

  const [toasts, setToasts] = createSignal<Toast[]>([]);
  let nextId = 0;

  function addToast(message: string, level: "info" | "error") {
    const id = nextId++;
    setToasts((prev) => [...prev, { id, message, level }]);

    // Auto-dismiss
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, TOAST_DURATION);
  }

  function showToast(message: string) {
    addToast(message, "info");
  }

  function showError(message: string) {
    addToast(message, "error");
  }

  // Listen for toast messages from backend
  onMount(() => {
    backend.onToast((message, level) => {
      addToast(message, level);
    });
  });

  const value: ToastContextValue = {
    toasts,
    showToast,
    showError,
  };

  return <ToastProvider value={value}>{props.children}</ToastProvider>;
}
