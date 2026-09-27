// Client for the observability dashboard endpoints. Langfuse keys never reach the browser:
// the backend queries Langfuse and returns these shapes. VITE_USE_MOCK=true swaps in scripted data.

import type {
  ObservabilitySummary,
  ObservabilityTraceDetail,
  ObservabilityTraces,
} from "../types/observability";
import { ApiError } from "./http";

export interface ObservabilityClient {
  mode: "live" | "mock";
  getSummary(days: number, signal?: AbortSignal): Promise<ObservabilitySummary>;
  getTraces(days: number, limit: number, signal?: AbortSignal): Promise<ObservabilityTraces>;
  getTrace(id: string, signal?: AbortSignal): Promise<ObservabilityTraceDetail>;
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" }, signal });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText || "request failed"}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

const httpObservability: ObservabilityClient = {
  mode: "live",
  getSummary: (days, signal) => getJson(`/api/observability/summary?days=${days}`, signal),
  getTraces: (days, limit, signal) =>
    getJson(`/api/observability/traces?days=${days}&limit=${limit}`, signal),
  getTrace: (id, signal) => getJson(`/api/observability/traces/${encodeURIComponent(id)}`, signal),
};

/** The mock is loaded on demand so live builds never ship its data in the main path. */
export async function loadObservabilityClient(): Promise<ObservabilityClient> {
  if (import.meta.env.VITE_USE_MOCK !== "true") return httpObservability;
  const { mockObservability } = await import("./observabilityMock");
  return mockObservability;
}
