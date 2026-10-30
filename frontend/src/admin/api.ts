import { authenticated } from "../api/client";
export interface Clock {
  business_now: string;
  real_now: string;
  offset_seconds: number;
  version: number;
  demo_mode: boolean;
}
export interface SweepResult {
  scanned: number;
  expired: number;
  checked_in: number;
  completed: number;
  paid: number;
  deferred: number;
  has_more: boolean;
}
export interface AuditEvent {
  id: string;
  actor_id: string | null;
  system_identity: string | null;
  action: string;
  target_type: string;
  target_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown>;
  business_at: string;
  recorded_at: string;
}
export const adminApi = {
  clock: () => authenticated<Clock>("/admin/demo/clock"),
  advance: (seconds: number, key: string) =>
    authenticated<{ clock: Clock; sweep: SweepResult }>("/admin/demo/advance", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({ seconds }),
    }),
  sweep: () =>
    authenticated<{ sweep: SweepResult }>("/admin/demo/sweep", {
      method: "POST",
      body: JSON.stringify({ batch_size: 100 }),
    }),
  events: (action: string, target_id: string, cursor?: string) =>
    authenticated<{ items: AuditEvent[]; next_cursor: string | null }>(
      `/admin/events?${new URLSearchParams({ ...(action ? { action } : {}), ...(target_id ? { target_id } : {}), ...(cursor ? { cursor } : {}) })}`,
    ),
};
