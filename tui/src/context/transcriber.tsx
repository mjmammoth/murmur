import {
  createSignal,
  onCleanup,
  onMount,
  untrack,
  type JSX,
  type Accessor,
} from "solid-js";
import { createContextHelper } from "./helper";
import { useBackend } from "./backend";
import type { TranscriptEntry, AppStatus } from "../types";
import { mergeAndDedupeTranscripts } from "./transcriber-merge";

export interface TranscriberContextValue {
  transcripts: Accessor<TranscriptEntry[]>;
  selectedIndex: Accessor<number>;
  status: Accessor<AppStatus>;
  statusMessage: Accessor<string>;
  statusElapsed: Accessor<number | undefined>;
  isRecording: Accessor<boolean>;
  isBusy: Accessor<boolean>;
  selectNext: () => void;
  selectPrev: () => void;
  selectIndex: (index: number) => void;
  getSelected: () => TranscriptEntry | null;
  getLatest: () => TranscriptEntry | null;
  copyText: (text: string) => void;
}

const [TranscriberProvider, useTranscriber] =
  createContextHelper<TranscriberContextValue>("Transcriber");
export { useTranscriber };

export function TranscriberContextProvider(props: {
  children: JSX.Element;
}): JSX.Element {
  const backend = useBackend();

  const [transcripts, setTranscripts] = createSignal<TranscriptEntry[]>([]);
  const [selectedIndex, setSelectedIndex] = createSignal(-1);

  // Computed status values
  const isRecording = () => backend.status() === "recording";
  const isBusy = () => {
    const s = backend.status();
    return s === "transcribing" || s === "downloading";
  };

  // Listen for transcripts from backend
  onMount(() => {
    const disposeTranscriptHistory = backend.onTranscriptHistory((entries) => {
      const previous = untrack(() => transcripts());
      const next = mergeAndDedupeTranscripts(entries, previous);
      setTranscripts(next);
      setSelectedIndex(next.length > 0 ? next.length - 1 : -1);
    });

    const disposeTranscript = backend.onTranscript((entry) => {
      const previous = untrack(() => transcripts());
      const next = mergeAndDedupeTranscripts(previous, [entry]);
      setTranscripts(next);
      setSelectedIndex(next.length > 0 ? next.length - 1 : -1);
    });

    onCleanup(() => {
      disposeTranscriptHistory();
      disposeTranscript();
    });
  });

  function selectNext() {
    const list = transcripts();
    if (list.length === 0) return;
    setSelectedIndex((idx) => Math.min(idx + 1, list.length - 1));
  }

  function selectPrev() {
    const list = transcripts();
    if (list.length === 0) return;
    setSelectedIndex((idx) => Math.max(idx - 1, 0));
  }

  function selectIndex(index: number) {
    const list = transcripts();
    if (list.length === 0) {
      setSelectedIndex(-1);
      return;
    }
    setSelectedIndex(Math.max(0, Math.min(index, list.length - 1)));
  }

  function getSelected(): TranscriptEntry | null {
    const idx = selectedIndex();
    const list = transcripts();
    if (idx < 0 || idx >= list.length) return null;
    return list[idx];
  }

  function getLatest(): TranscriptEntry | null {
    const list = transcripts();
    if (list.length === 0) return null;
    return list[list.length - 1];
  }

  function copyText(text: string) {
    backend.send({ type: "copy_text", text });
  }

  const value: TranscriberContextValue = {
    transcripts,
    selectedIndex,
    status: backend.status,
    statusMessage: backend.statusMessage,
    statusElapsed: backend.statusElapsed,
    isRecording,
    isBusy,
    selectNext,
    selectPrev,
    selectIndex,
    getSelected,
    getLatest,
    copyText,
  };

  return <TranscriberProvider value={value}>{props.children}</TranscriberProvider>;
}
