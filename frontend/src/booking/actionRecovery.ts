const prefix = "stayhub-action-v1:";
export function readAction<T>(operation: string, actor: string): T | null {
  try {
    const raw = sessionStorage.getItem(prefix + operation);
    if (!raw) return null;
    const value = JSON.parse(raw) as { actor: string; payload: T };
    if (value.actor !== actor) {
      sessionStorage.removeItem(prefix + operation);
      return null;
    }
    return value.payload;
  } catch {
    return null;
  }
}
export function saveAction<T>(operation: string, actor: string, payload: T) {
  sessionStorage.setItem(
    prefix + operation,
    JSON.stringify({ actor, payload }),
  );
}
export function clearAction(operation: string) {
  try {
    sessionStorage.removeItem(prefix + operation);
  } catch {
    /* unavailable storage */
  }
}
export function clearOtherActorActions(actor?: string) {
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const key = sessionStorage.key(i);
      if (key?.startsWith(prefix)) {
        const raw = sessionStorage.getItem(key);
        if (!actor || !raw || JSON.parse(raw).actor !== actor)
          sessionStorage.removeItem(key);
      }
    }
  } catch {
    /* unavailable storage */
  }
}
