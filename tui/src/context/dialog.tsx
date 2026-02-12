import { createSignal, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";
import type { DialogType, DialogState } from "../types";

export interface DialogContextValue {
  currentDialog: Accessor<DialogState | null>;
  isOpen: Accessor<boolean>;
  openDialog: (type: DialogType, data?: unknown) => void;
  closeDialog: () => void;
}

const [DialogProvider, useDialog] = createContextHelper<DialogContextValue>("Dialog");
export { useDialog };

export function DialogContextProvider(props: { children: JSX.Element }): JSX.Element {
  const [currentDialog, setCurrentDialog] = createSignal<DialogState | null>(null);

  const isOpen = () => currentDialog() !== null;

  function openDialog(type: DialogType, data?: unknown) {
    setCurrentDialog({ type, data });
  }

  function closeDialog() {
    setCurrentDialog(null);
  }

  const value: DialogContextValue = {
    currentDialog,
    isOpen,
    openDialog,
    closeDialog,
  };

  return <DialogProvider value={value}>{props.children}</DialogProvider>;
}
