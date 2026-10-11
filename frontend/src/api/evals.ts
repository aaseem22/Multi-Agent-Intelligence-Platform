// Client for the offline eval harness and live self-evaluation (backend/app/evals/API.md).
// VITE_USE_MOCK=true swaps in scripted data, loaded on demand so live builds never ship it.

import type {
  CalibrationStats,
  Dataset,
  HumanLabel,
  HumanLabelRequest,
  RunConfig,
  RunProgress,
  RunSummary,
  SelfEvalStats,
  TrialResult,
} from "../types/evals";
import { ApiError } from "./http";

export interface EvalsClient {
  mode: "live" | "mock";
  getDatasets(signal?: AbortSignal): Promise<Dataset[]>;
  getRuns(signal?: AbortSignal): Promise<RunSummary[]>;
  startRun(config: RunConfig): Promise<RunSummary>;
  getRun(runId: string, signal?: AbortSignal): Promise<RunSummary>;
  getProgress(runId: string, signal?: AbortSignal): Promise<RunProgress>;
  cancelRun(runId: string): Promise<void>;
  getTrials(runId: string, signal?: AbortSignal): Promise<TrialResult[]>;
  getTrial(runId: string, trialId: string, signal?: AbortSignal): Promise<TrialResult>;
  getLabels(runId: string, signal?: AbortSignal): Promise<HumanLabel[]>;
  putLabel(runId: string, label: HumanLabelRequest): Promise<HumanLabel>;
  getCalibration(signal?: AbortSignal): Promise<CalibrationStats>;
  getSelfEval(days: number, signal?: AbortSignal): Promise<SelfEvalStats>;
}

async function failure(response: Response): Promise<ApiError> {
  let detail = `${response.status} ${response.statusText || "request failed"}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) detail = body.detail.map((item) => (item as { msg?: string }).msg ?? "").join(" ");
  } catch {
    // keep the status text
  }
  return new ApiError(response.status, detail);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}) },
  });
  if (!response.ok) throw await failure(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const enc = encodeURIComponent;
const run = (id: string) => `/api/evals/runs/${enc(id)}`;

const httpEvals: EvalsClient = {
  mode: "live",
  getDatasets: (signal) => request("/api/evals/datasets", { signal }),
  getRuns: (signal) => request("/api/evals/runs", { signal }),
  startRun: (config) => request("/api/evals/runs", { method: "POST", body: JSON.stringify(config) }),
  getRun: (id, signal) => request(run(id), { signal }),
  getProgress: (id, signal) => request(`${run(id)}/progress`, { signal }),
  cancelRun: (id) => request(`${run(id)}/cancel`, { method: "POST" }),
  getTrials: (id, signal) => request(`${run(id)}/trials`, { signal }),
  getTrial: (id, trialId, signal) => request(`${run(id)}/trials/${enc(trialId)}`, { signal }),
  getLabels: (id, signal) => request(`${run(id)}/labels`, { signal }),
  putLabel: (id, label) => request(`${run(id)}/labels`, { method: "POST", body: JSON.stringify(label) }),
  getCalibration: (signal) => request("/api/evals/calibration", { signal }),
  getSelfEval: (days, signal) => request(`/api/evals/self-eval?days=${days}`, { signal }),
};

let client: Promise<EvalsClient> | null = null;

/** One client per page load; the mock module is only fetched in mock mode. */
export function evalsClient(): Promise<EvalsClient> {
  client ??=
    import.meta.env.VITE_USE_MOCK === "true"
      ? import("./evalsMock").then((module) => module.mockEvals)
      : Promise.resolve(httpEvals);
  return client;
}
