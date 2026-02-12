import { $ } from "bun";

/**
 * Copy text to system clipboard using pbcopy (macOS).
 * Falls back silently if clipboard operations fail.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    // macOS pbcopy
    await $`echo ${text} | pbcopy`.quiet();
    return true;
  } catch {
    // Silently fail if clipboard is unavailable
    return false;
  }
}
