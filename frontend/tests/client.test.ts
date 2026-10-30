import { beforeEach, describe, expect, it, vi } from "vitest";
const user = {
  id: "user-id",
  name: "Test Guest",
  email: "test@example.com",
  roles: ["guest"],
};
const auth = {
  user,
  access_token: "test-access",
  token_type: "bearer",
  expires_in: 900,
  csrf_token: "csrf",
};
function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
const denied = {
  error: {
    code: "unauthorized",
    message: "Sign in again",
    field_errors: null,
    request_id: "request",
  },
};
beforeEach(() => {
  vi.resetModules();
  vi.unstubAllGlobals();
});
describe("auth transport", () => {
  it("serializes login after pending bootstrap to avoid stale cookie responses", async () => {
    let resolveCsrf!: (response: Response) => void;
    const waiting = new Promise<Response>((resolve) => {
      resolveCsrf = resolve;
    });
    const fetch = vi
      .fn()
      .mockReturnValueOnce(waiting)
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(auth));
    vi.stubGlobal("fetch", fetch);
    const client = await import("../src/api/client");
    const restoring = client.refresh();
    const signingIn = client.login("test@example.com", "test");
    expect(fetch).toHaveBeenCalledTimes(1);
    resolveCsrf(json({ csrf_token: "old-session" }));
    await Promise.all([restoring, signingIn]);
    expect(client.sessionStore.snapshot().user).toEqual(user);
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/auth/csrf",
      "/api/v1/auth/refresh",
      "/api/v1/auth/login",
    ]);
  });
  it("coordinates concurrent refresh and restores memory state", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf" }))
      .mockResolvedValueOnce(json(auth));
    vi.stubGlobal("fetch", fetch);
    const client = await import("../src/api/client");
    await Promise.all([client.refresh(), client.refresh()]);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(client.sessionStore.snapshot().user?.name).toBe("Test Guest");
    expect(localStorage.length).toBe(0);
  });
  it("keeps authenticated state when logout encounters a network failure", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(auth))
      .mockRejectedValueOnce(new TypeError("network"));
    vi.stubGlobal("fetch", fetch);
    const client = await import("../src/api/client");
    await client.login("test@example.com", "test");
    await expect(client.logout()).rejects.toThrow("Unable to connect");
    expect(client.sessionStore.snapshot().user).toEqual(user);
  });
  it("clears private identity on definitive refresh rejection", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(denied, 401));
    vi.stubGlobal("fetch", fetch);
    const client = await import("../src/api/client");
    await client.login("test@example.com", "test");
    await expect(client.refresh()).rejects.toThrow("Sign in again");
    expect(client.sessionStore.snapshot().user).toBeNull();
  });
  it("retries an unauthorized request once and does not loop", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(denied, 401))
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(denied, 401));
    vi.stubGlobal("fetch", fetch);
    const client = await import("../src/api/client");
    await client.login("test@example.com", "test");
    await expect(client.authenticated("/auth/me")).rejects.toThrow(
      "Sign in again",
    );
    expect(fetch).toHaveBeenCalledTimes(4);
  });
  it("never replays a mutation after a transport failure", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(auth))
      .mockRejectedValueOnce(new TypeError("network"));
    vi.stubGlobal("fetch", fetch);
    const client = await import("../src/api/client");
    await client.login("test@example.com", "test");
    await expect(client.startHosting()).rejects.toThrow("Unable to connect");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("rejects external and protocol-relative return paths", async () => {
    const { safeReturnPath } = await import("../src/api/client");
    for (const path of [
      "https://evil.test",
      "//evil.test",
      "/\\evil.test",
      "/%2f%2fevil.test",
      "/%5cevil.test",
      "/%0aevil.test",
      "/%ZZ",
    ])
      expect(safeReturnPath(path)).toBe("/profile");
    expect(safeReturnPath("/host/today")).toBe("/host/today");
  });
});
