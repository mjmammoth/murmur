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
