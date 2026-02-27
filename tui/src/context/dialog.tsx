import { createSignal, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";
import type { DialogType, DialogState } from "../types";

interface DialogDismissRegistration {
  type: DialogType;
  handler: () => void;
}

export interface DialogContextValue {
  currentDialog: Accessor<DialogState | null>;
  isOpen: Accessor<boolean>;
  openDialog: (type: DialogType, data?: unknown) => void;
  closeDialog: () => void;
  requestDismiss: () => void;
  registerDismissHandler: (type: DialogType, handler: () => void) => () => void;
}

const [DialogProvider, useDialog] = createContextHelper<DialogContextValue>("Dialog");
export { useDialog };

/**
 * Provides a Dialog context to its subtree and manages dialog visibility and dismissal behavior.
 *
 * The provider exposes the current dialog state and helpers to open and close dialogs, request a dismissal
 * (which will invoke a registered dismiss handler for the active dialog type if present), and register a
 * one-shot dismiss handler for a specific dialog type.
 *
 * @param props - Component props.
 * @param props.children - The subtree that will receive the dialog context.
 * @returns A JSX element that renders the Dialog context provider wrapping `children`.
 */
export function DialogContextProvider(props: { children: JSX.Element }): JSX.Element {
  const [currentDialog, setCurrentDialog] = createSignal<DialogState | null>(null);
  const [dismissRegistration, setDismissRegistration] = createSignal<DialogDismissRegistration | null>(null);

  const isOpen = () => currentDialog() !== null;

  function openDialog(type: DialogType, data?: unknown) {
    setDismissRegistration(null);
    setCurrentDialog({ type, data });
  }

  function closeDialog() {
    setDismissRegistration(null);
    setCurrentDialog(null);
  }

  function requestDismiss() {
    const current = currentDialog();
    if (!current) return;

    const registration = dismissRegistration();
    if (registration && registration.type === current.type) {
      registration.handler();
      setDismissRegistration((registered) => {
        if (!registered) return registered;
        if (registered.type !== registration.type || registered.handler !== registration.handler) {
          return registered;
        }
        return null;
      });
      return;
    }

    closeDialog();
  }

  function registerDismissHandler(type: DialogType, handler: () => void) {
    setDismissRegistration({ type, handler });
    return () => {
      setDismissRegistration((current) => {
        if (!current) return current;
        if (current.type !== type || current.handler !== handler) return current;
        return null;
      });
    };
  }

  const value: DialogContextValue = {
    currentDialog,
    isOpen,
    openDialog,
    closeDialog,
    requestDismiss,
    registerDismissHandler,
  };

  return <DialogProvider value={value}>{props.children}</DialogProvider>;
}
