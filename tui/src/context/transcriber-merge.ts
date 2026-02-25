import type { TranscriptEntry } from "../types";

export function transcriptIdentity(entry: TranscriptEntry): string {
  if (typeof entry.id === "number") {
    return `id:${entry.id}`;
  }
  return `timestamp:${entry.timestamp}`;
}

export function mergeAndDedupeTranscripts(
  primary: readonly TranscriptEntry[],
  secondary: readonly TranscriptEntry[],
): TranscriptEntry[] {
  const merged: TranscriptEntry[] = [];
  const seen = new Set<string>();
  for (const entry of [...primary, ...secondary]) {
    const idKey = typeof entry.id === "number" ? `id:${entry.id}` : null;
    const timestampKey = `timestamp:${entry.timestamp}`;
    if ((idKey !== null && seen.has(idKey)) || seen.has(timestampKey)) continue;
    if (idKey !== null) {
      seen.add(idKey);
    }
    seen.add(timestampKey);
    merged.push(entry);
  }
  return merged;
}
