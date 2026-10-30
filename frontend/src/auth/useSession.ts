import { useSyncExternalStore } from "react";
import { sessionStore } from "../api/client";
export function useSession() {
  return useSyncExternalStore(sessionStore.subscribe, sessionStore.snapshot);
}
