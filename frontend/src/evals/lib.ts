import { evalsClient, type EvalsClient } from "../api/evals";
import { useResource, type Resource } from "../hooks/useResource";
import type { GraderKind, RunStatus, RunSummary, TrialResult } from "../types/evals";

/** Loads evals data through the (possibly lazily imported mock) client. */
export function useEvals<T>(
  fetcher: (client: EvalsClient, signal: AbortSignal) => Promise<T>,
  key: string,
): [Resource<T>, () => void] {
  return useResource((signal) => evalsClient().then((client) => fetcher(client, signal)), key);
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

export function fmtScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return value.toFixed(2);
}

const NAMES: Record<string, string> = { a2a: "Agent to agent", "single-domain": "Single department", "cross-domain": "Cross department" };

export function humanise(name: string): string {
  if (NAMES[name]) return NAMES[name];
  const words = name.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function duration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export const SUITE_COPY = {
  capability: {
    label: "Capability",
    line: "A hill to climb: tasks the system cannot reliably do yet. A low score here is expected.",
  },
  regression: {
    label: "Regression",
    line: "Tasks it already handles. These should stay near 100%; any drop is a break.",
  },
} as const;

export const KIND_COPY: Record<GraderKind, { label: string; line: string }> = {
  code: { label: "Code graders", line: "Deterministic checks: routing, peer messages, required facts, evidence." },
  model: { label: "Model graders", line: "The judge model scores a rubric per dimension. Calibrate it with human labels." },
  human: { label: "Human graders", line: "Your own verdicts, used to check the judge." },
};

export function isActive(status: RunStatus): boolean {
  return status === "queued" || status === "running";
}

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export type MarkState = "pass" | "fail" | "error" | "unknown";

export function trialState(trial: Pick<TrialResult, "status">): MarkState {
  return trial.status === "passed" ? "pass" : trial.status === "error" ? "error" : "fail";
}

/** The most recent completed run, or null. Runs arrive newest first. */
export function latestCompleted(runs: RunSummary[]): RunSummary | null {
  return runs.find((run) => run.status === "completed") ?? null;
}

/** Grader name to kind, read from trial results (run summaries only carry grader names). */
export function graderKinds(trials: TrialResult[]): Map<string, GraderKind> {
  const kinds = new Map<string, GraderKind>();
  for (const trial of trials) for (const grader of trial.graders) kinds.set(grader.grader, grader.kind);
  return kinds;
}

const MODEL_HINT = /judge|model|quality|rubric|reference|llm/i;

export function kindOf(name: string, kinds: Map<string, GraderKind>): GraderKind {
  return kinds.get(name) ?? (MODEL_HINT.test(name) ? "model" : "code");
}

export function configSummary(run: RunSummary): string {
  const { config } = run;
  const suites = config.suites.length === 2 ? "both suites" : `${config.suites[0] ?? "no"} suite`;
  const subset = config.task_ids.length > 0 ? `${config.task_ids.length} picked tasks` : `${run.tasks_total} tasks`;
  return `${config.dataset} v${run.dataset_version}, ${suites}, ${subset}, k=${config.trials}, judge ${config.judge_enabled ? "on" : "off"}, recovery ${config.self_eval_recovery}`;
}

/** Free-tier budget: about 13 Gemini requests a minute, about 15 calls per task trial. */
export const REQUESTS_PER_MINUTE = 13;
export const CALLS_PER_TRIAL = 15;

export function estimateMinutes(tasks: number, trials: number): number {
  return Math.ceil((tasks * trials * CALLS_PER_TRIAL) / REQUESTS_PER_MINUTE);
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}
