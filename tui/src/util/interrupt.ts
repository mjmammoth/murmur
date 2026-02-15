let sigintHandler: (() => void) | null = null;

export function setSigintHandler(handler: (() => void) | null): void {
  sigintHandler = handler;
}

export function handleSigint(): boolean {
  if (!sigintHandler) return false;
  sigintHandler();
  return true;
}
