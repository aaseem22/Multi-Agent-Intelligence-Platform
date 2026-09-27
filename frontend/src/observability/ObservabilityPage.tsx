import "@fontsource-variable/saira/wdth.css";
import "@fontsource-variable/jetbrains-mono/index.css";
import "./obs.css";

import { ArrowLeft, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { observabilityHref } from "../hooks/useHashRoute";
import { AgentReadout } from "./AgentReadout";
import { Constellation } from "./Constellation";
import { REFRESH_MS, useDashboard, useReducedMotion } from "./hooks";
import { BootState, DisabledState, EmptyState, ErrorState } from "./HudStates";
import { Reactor } from "./Reactor";
import { Telemetry } from "./Telemetry";
import { TraceFeed } from "./TraceFeed";
import { TraceInspector } from "./TraceInspector";

const WINDOWS = [
  { days: 1, label: "24h" },
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
];

function Mark() {
  return (
    <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden>
      <circle cx="15" cy="15" r="13" fill="none" stroke="var(--obs-ice-dim)" strokeWidth="1" strokeDasharray="2 2.5" />
      <circle cx="15" cy="15" r="9" fill="none" stroke="var(--obs-ice)" strokeWidth="1.5" />
      <circle cx="15" cy="15" r="4" fill="var(--obs-ice)" style={{ filter: "drop-shadow(0 0 4px rgba(127,220,255,0.9))" }} />
    </svg>
  );
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

function RefreshIndicator({
  cycle,
  updatedAt,
  refreshing,
  error,
  onRefresh,
}: {
  cycle: number;
  updatedAt: number | null;
  refreshing: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  const now = useNow(1000);
  const reduced = useReducedMotion();
  const seconds = updatedAt ? Math.max(0, Math.round((now - updatedAt) / 1000)) : null;
  const length = 2 * Math.PI * 7;
  const label = refreshing
    ? "Refreshing"
    : error
      ? "Refresh failed, showing earlier data"
      : seconds == null
        ? "Waiting for data"
        : `Updated ${seconds < 2 ? "just now" : `${seconds}s ago`}`;
  return (
    <div className="flex items-center gap-3">
      <span className="flex items-center gap-2" title={`Refreshes every ${REFRESH_MS / 1000} seconds`}>
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden className={refreshing ? "obs-sweep-fast" : undefined}>
          <circle cx="9" cy="9" r="7" fill="none" stroke="var(--obs-line-strong)" strokeWidth="2" />
          {refreshing ? (
            <path d="M9 2 A7 7 0 0 1 16 9" fill="none" stroke="var(--obs-ice)" strokeWidth="2" strokeLinecap="round" />
          ) : (
            <circle
              key={cycle}
              cx="9"
              cy="9"
              r="7"
              fill="none"
              stroke={error ? "var(--obs-amber)" : "var(--obs-ice)"}
              strokeWidth="2"
              strokeDasharray={length}
              transform="rotate(-90 9 9)"
              style={
                reduced
                  ? undefined
                  : ({ "--obs-len": `${length}`, animation: `obs-countdown ${REFRESH_MS}ms linear forwards` } as React.CSSProperties)
              }
            />
          )}
        </svg>
        <span className={`obs-mono text-xs ${error ? "obs-amber" : "obs-t2"}`} aria-live="polite" title={error ?? undefined}>
          {label}
        </span>
      </span>
      <button type="button" onClick={onRefresh} className="obs-button" disabled={refreshing} aria-label="Refresh now">
        <RefreshCw size={14} aria-hidden />
        <span className="hidden sm:inline">Refresh</span>
      </button>
    </div>
  );
}

export default function ObservabilityPage({
  traceId,
  navigate,
}: {
  traceId: string | null;
  navigate: (href: string) => void;
}) {
  const [days, setDays] = useState(7);
  const [state, refresh] = useDashboard(days);
  const summary = state.data?.summary ?? null;
  const traces = state.data?.traces ?? null;

  const select = useCallback((id: string) => navigate(observabilityHref(id)), [navigate]);
  const close = useCallback(() => navigate(observabilityHref(null)), [navigate]);

  const disabled = summary && !summary.enabled ? summary : traces && !traces.enabled ? traces : null;
  const empty = summary?.enabled && summary.traces === 0 && (traces?.traces.length ?? 0) === 0;

  let body;
  if (state.status === "loading" && !state.data) body = <BootState />;
  else if (state.status === "error" && !state.data) body = <ErrorState message={state.error ?? "Unknown error"} onRetry={refresh} />;
  else if (disabled) body = <DisabledState reason={disabled.reason} onRetry={refresh} />;
  else if (empty || !summary || !traces) body = <EmptyState days={days} onWiden={days < 30 ? () => setDays(30) : null} />;
  else
    body = (
      <main className="obs-grid" aria-label="Trace telemetry">
        <div className="obs-main">
          <Reactor summary={summary} />
          <Constellation summary={summary} />
          <Telemetry summary={summary} />
          <AgentReadout summary={summary} />
        </div>
        <TraceFeed traces={traces.traces} selectedId={traceId} onSelect={select} supervisor={summary.supervisor} />
      </main>
    );

  return (
    <div className="obs-root">
      <header className="obs-header">
        <a href="#/chat" className="obs-button !px-2" aria-label="Back to the console">
          <ArrowLeft size={16} aria-hidden />
        </a>
        <div className="flex items-center gap-3">
          <Mark />
          <div>
            <h1 className="obs-title">Trace telemetry</h1>
            <p className="obs-cond obs-t3 mt-1 text-xs">
              Stakeholder requests as traced in Langfuse
              {state.mode === "mock" ? <span className="obs-amber"> (mock data)</span> : null}
            </p>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-2">
          <div className="obs-segment" role="group" aria-label="Time window">
            {WINDOWS.map((w) => (
              <button key={w.days} type="button" aria-pressed={w.days === days} onClick={() => setDays(w.days)}>
                {w.label}
              </button>
            ))}
          </div>
          <RefreshIndicator
            cycle={state.cycle}
            updatedAt={state.updatedAt}
            refreshing={state.refreshing}
            error={state.data ? state.error : null}
            onRefresh={refresh}
          />
          {summary?.enabled && summary.host ? (
            <a href={summary.host} target="_blank" rel="noreferrer" className="obs-cond obs-t2 hidden text-sm underline decoration-(--obs-line-strong) underline-offset-4 hover:text-(--obs-text) lg:inline">
              Langfuse project
            </a>
          ) : null}
        </div>
      </header>
      {body}
      {traceId ? <TraceInspector traceId={traceId} onClose={close} supervisor={summary?.supervisor ?? null} /> : null}
    </div>
  );
}
