import { clearOtherActorActions } from "../booking/actionRecovery";
import type { AuthResponse, ErrorEnvelope, User } from "./types";
export class ApiError extends Error {
  constructor(
    public status: number,
    public details: ErrorEnvelope["error"],
  ) {
    super(details.message);
  }
}
export type SessionState = {
  user: User | null;
  ready: boolean;
  error: string | null;
};
let sessionVersion = 0;
let accessToken: string | null = null;
let csrfToken: string | null = null;
let state: SessionState = { user: null, ready: false, error: null };
const listeners = new Set<() => void>();
let refreshFlight: Promise<void> | null = null;
function publish(next: SessionState) {
  state = next;
  listeners.forEach((fn) => fn());
}
export const sessionStore = {
  subscribe: (fn: () => void) => {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
  snapshot: () => state,
};
function clear() {
  sessionVersion++;
  accessToken = null;
  csrfToken = null;
  publish({ user: null, ready: true, error: null });
}
function accept(data: AuthResponse) {
  sessionVersion++;
  accessToken = data.access_token;
  csrfToken = data.csrf_token;
  publish({ user: data.user, ready: true, error: null });
}
export async function publicRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...init,
      credentials: "same-origin",
      signal: init.signal ?? AbortSignal.timeout(15000),
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new Error(
      "Unable to connect to StayHub. Check your connection and try again.",
    );
  }
  if (!response.ok) {
    let envelope: ErrorEnvelope;
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      envelope = {
        error: {
          code: "unavailable",
          message: "StayHub could not complete this request. Please try again.",
          field_errors: null,
          request_id: "",
        },
      };
    }
    throw new ApiError(response.status, envelope.error);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}
export function refresh(): Promise<void> {
  if (refreshFlight) return refreshFlight;
  const expectedVersion = sessionVersion;
  refreshFlight = (async () => {
    try {
      if (!csrfToken) {
        const data = await publicRequest<{ csrf_token: string }>("/auth/csrf");
        if (sessionVersion !== expectedVersion) return;
        csrfToken = data.csrf_token;
      }
      const refreshed = await publicRequest<AuthResponse>("/auth/refresh", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
      });
      if (sessionVersion === expectedVersion) accept(refreshed);
    } catch (error) {
      if (sessionVersion !== expectedVersion) return;
      if (error instanceof ApiError && error.status === 401) {
        clear();
      } else {
        publish({
          ...state,
          ready: true,
          error:
            error instanceof Error
              ? error.message
              : "Could not restore your session.",
        });
      }
      throw error;
    } finally {
      refreshFlight = null;
    }
  })();
  return refreshFlight;
}
let bootstrapFlight: Promise<void> | null = null;
export function bootstrap() {
  bootstrapFlight ??= refresh().catch(() => {});
  return bootstrapFlight;
}
export async function login(email: string, password: string) {
  // Serialize cookie-setting operations so late refresh responses cannot replace a newer login cookie.
  if (refreshFlight) await refreshFlight.catch(() => {});
  accept(
    await publicRequest<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  );
}
export class RegisteredLoginError extends Error {
  constructor() {
    super(
      "Your account was created, but we could not log you in. Log in below to continue.",
    );
  }
}
export async function register(name: string, email: string, password: string) {
  await publicRequest<{ user: User }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ name, email, password }),
  });
  try {
    await login(email, password);
  } catch {
    throw new RegisteredLoginError();
  }
}
export async function authenticated<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  try {
    return await publicRequest<T>(path, {
      ...init,
      headers: {
        ...init.headers,
        Authorization: `Bearer ${accessToken ?? ""}`,
      },
    });
  } catch (error) {
    // Only a rejected authentication request is replayed, once. No transport-error mutation retries.
    if (retry && error instanceof ApiError && error.status === 401) {
      await refresh();
      if (!accessToken) throw error;
      return authenticated<T>(path, init, false);
    }
    throw error;
  }
}
export async function startHosting() {
  const data = await authenticated<{ user: User }>("/me/host-role", {
    method: "POST",
  });
  publish({ ...state, user: data.user });
}
export async function logout() {
  if (refreshFlight) await refreshFlight.catch(() => {});
  if (!csrfToken) {
    const data = await publicRequest<{ csrf_token: string }>(
      "/auth/csrf",
    ).catch((error) => {
      if (error instanceof ApiError && error.status === 401) return null;
      throw error;
    });
    csrfToken = data?.csrf_token ?? null;
  }
  await publicRequest<void>("/auth/logout", {
    method: "POST",
    headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
  });
  try {
    sessionStorage.removeItem("stayhub-pay-submission-v1");
  } catch {
    /* Logout must still clear the in-memory session. */
  }
  clearOtherActorActions();
  clear();
}
export function safeReturnPath(value: string | null) {
  if (!value || !value.startsWith("/") || value.startsWith("//"))
    return "/profile";
  try {
    const decoded = decodeURIComponent(value);
    if (
      decoded.startsWith("//") ||
      decoded.includes("\\") ||
      Array.from(decoded).some(
        (character) =>
          character.charCodeAt(0) <= 32 || character.charCodeAt(0) === 127,
      )
    )
      return "/profile";
    const target = new URL(value, "https://stayhub.invalid");
    return target.origin === "https://stayhub.invalid"
      ? target.pathname + target.search + target.hash
      : "/profile";
  } catch {
    return "/profile";
  }
}
