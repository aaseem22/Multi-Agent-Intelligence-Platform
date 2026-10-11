import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { loadObservabilityClient, type ObservabilityClient } from "../api/observability";
import { errorMessage, isAbortError } from "../lib/format";
import type {
  ObservabilitySummary,
  ObservabilityTraceDetail,
  ObservabilityTraces,
} from "../types/observability";

export const REFRESH_MS = 20_000;
const TRACE_LIMIT = 50;

// --- Reduced motion ------------------------------------------------------------------------------

const motionQuery = "(prefers-reduced-motion: reduce)";

function subscribeMotion(onChange: () => void): () => void {
  const media = window.matchMedia(motionQuery);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeMotion, () => window.matchMedia(motionQuery).matches);
}

// --- Count-up numbers ----------------------------------------------------------------------------

/** Animates from the previously shown value to `target`. Instant when motion is reduced. */
export function useCountUp(target: number, duration = 900): number {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(0);
  const shownRef = useRef(0);

  useEffect(() => {
    if (reduced) {
      shownRef.current = target;
      return;
    }
    const from = shownRef.current;
    if (from === target) return;
    const started = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min((now - started) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = from + (target - from) * eased;
      shownRef.current = value;
      setShown(value);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    // Background tabs and headless renderers may never fire rAF: land on the target regardless.
    const settle = window.setTimeout(() => {
      cancelAnimationFrame(frame);
      shownRef.current = target;
      setShown(target);
    }, duration + 100);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(settle);
    };
  }, [target, duration, reduced]);

  return reduced ? target : shown;
}

// --- Client ------------------------------------------------------------------------------------

let clientPromise: Promise<ObservabilityClient> | null = null;
function client(): Promise<ObservabilityClient> {
  clientPromise ??= loadObservabilityClient();
  return clientPromise;
}

// --- Dashboard data ------------------------------------------------------------------------------

export interface DashboardData {
  summary: ObservabilitySummary;
  traces: ObservabilityTraces;
}

export interface DashboardState {
  status: "loading" | "ready" | "error";
  data: DashboardData | null;
  error: string | null;
  refreshing: boolean;
  updatedAt: number | null;
  /** Increments on every completed load; keys the refresh-countdown ring. */
  cycle: number;
  mode: "live" | "mock" | null;
}

/** Summary + recent traces for a window, refreshed every 20 s while the tab is visible. */
export function useDashboard(days: number): [DashboardState, () => void] {
  const [state, setState] = useState<DashboardState>({
    status: "loading",
    data: null,
    error: null,
    refreshing: true,
    updatedAt: null,
    cycle: 0,
    mode: null,
  });
  const [attempt, setAttempt] = useState(0);
  const [loadedDays, setLoadedDays] = useState(days);

  if (loadedDays !== days) {
    setLoadedDays(days);
    setState((previous) => ({ ...previous, status: "loading", data: null, error: null, refreshing: true }));
  }

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      const api = await client();
      const [summary, traces] = await Promise.all([
        api.getSummary(days, controller.signal),
        api.getTraces(days, TRACE_LIMIT, controller.signal),
      ]);
      return { api, summary, traces };
    })().then(
      ({ api, summary, traces }) =>
        setState((previous) => {
          // A temporary Langfuse outage must not blank a dashboard that already has data:
          // keep the last good result on screen and report the refresh as failed.
          const blip = [summary, traces].find((part) => !part.enabled && part.transient);
          if (blip && previous.data?.summary.enabled) {
            return {
              ...previous,
              status: "ready",
              error: blip.reason ?? "Langfuse is temporarily unreachable",
              refreshing: false,
              cycle: previous.cycle + 1,
            };
          }
          return {
            status: "ready",
            data: { summary, traces },
            error: null,
            refreshing: false,
            updatedAt: Date.now(),
            cycle: previous.cycle + 1,
            mode: api.mode,
          };
        }),
      (error: unknown) => {
        if (isAbortError(error)) return;
        setState((previous) => ({
          ...previous,
          status: previous.data ? "ready" : "error",
          error: errorMessage(error),
          refreshing: false,
          updatedAt: previous.updatedAt,
          cycle: previous.cycle + 1,
        }));
      },
    );
    return () => controller.abort();
  }, [days, attempt]);

  // Auto-refresh: schedule the next load after each completed one, skipping hidden tabs.
  useEffect(() => {
    if (state.cycle === 0) return;
    const timer = window.setTimeout(() => {
      if (document.visibilityState !== "visible") return;
      setState((previous) => ({ ...previous, refreshing: true }));
      setAttempt((value) => value + 1);
    }, REFRESH_MS);
    return () => window.clearTimeout(timer);
  }, [state.cycle]);

  const refresh = useCallback(() => {
    setState((previous) => ({ ...previous, refreshing: true }));
    setAttempt((value) => value + 1);
  }, []);
  return [state, refresh];
}

// --- Trace detail --------------------------------------------------------------------------------

export type TraceDetailState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; detail: ObservabilityTraceDetail };

export function useTraceDetail(traceId: string | null): [TraceDetailState, () => void] {
  const [state, setState] = useState<TraceDetailState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [loadedId, setLoadedId] = useState(traceId);

  if (loadedId !== traceId) {
    setLoadedId(traceId);
    setState({ status: "loading" });
  }

  useEffect(() => {
    if (!traceId) return;
    const controller = new AbortController();
    client()
      .then((api) => api.getTrace(traceId, controller.signal))
      .then(
        (detail) => setState({ status: "ready", detail }),
        (error: unknown) => {
          if (!isAbortError(error)) setState({ status: "error", error: errorMessage(error) });
        },
      );
    return () => controller.abort();
  }, [traceId, attempt]);

  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((value) => value + 1);
  }, []);
  return [state, retry];
}
