import "./obs.css";

import { Activity, ExternalLink, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { observabilityHref } from "../hooks/useHashRoute";
import { AgentReadout } from "./AgentReadout";
import { Constellation } from "./Constellation";
import { REFRESH_MS, useDashboard, useReducedMotion } from "./hooks";
import { BootState, DisabledState, EmptyState, ErrorState, UnreachableState } from "./HudStates";
import { Reactor } from "./Reactor";
import { Telemetry } from "./Telemetry";
import { TraceFeed } from "./TraceFeed";
import { TraceInspector } from "./TraceInspector";

const WINDOWS = [
  { days: 1, label: "24h" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];

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
  const length = 2 * Math.PI * 6;
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
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden className={refreshing ? "obs-sweep-fast" : undefined}>
          <circle cx="8" cy="8" r="6" fill="none" stroke="var(--obs-line)" strokeWidth="2" />
          {refreshing ? (
            <path d="M8 2 A6 6 0 0 1 14 8" fill="none" stroke="var(--obs-ice)" strokeWidth="2" strokeLinecap="round" />
          ) : (
            <circle
              key={cycle}
              cx="8"
              cy="8"
              r="6"
              fill="none"
              stroke={error ? "var(--obs-amber)" : "var(--obs-ice)"}
              strokeWidth="2"
              strokeDasharray={length}
              transform="rotate(-90 8 8)"
              style={
                reduced
                  ? undefined
                  : ({ "--obs-len": `${length}`, animation: `obs-countdown ${REFRESH_MS}ms linear forwards` } as React.CSSProperties)
              }
            />
          )}
        </svg>
        <span className={`text-xs ${error ? "obs-amber" : "obs-t3"}`} aria-live="polite" title={error ?? undefined}>
          {label}
        </span>
      </span>
      <button type="button" onClick={onRefresh} className="obs-button" disabled={refreshing} aria-label="Refresh now">
        <RefreshCw size={14} strokeWidth={1.75} aria-hidden />
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
  const [days, setDays] = useState(30);
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
  else if (disabled?.transient) body = <UnreachableState reason={disabled.reason} onRetry={refresh} />;
  else if (disabled) body = <DisabledState reason={disabled.reason} onRetry={refresh} />;
  else if (empty || !summary || !traces) body = <EmptyState days={days} onWiden={days < 30 ? () => setDays(30) : null} />;
  else
    body = (
      <div className="obs-grid" aria-label="Trace telemetry">
        <div className="obs-main">
          <Reactor summary={summary} />
          <Constellation summary={summary} />
          <Telemetry summary={summary} />
          <AgentReadout summary={summary} />
        </div>
        <TraceFeed traces={traces.traces} selectedId={traceId} onSelect={select} supervisor={summary.supervisor} />
      </div>
    );

  return (
    <div className="h-full overflow-y-auto">
      <div className="obs-root">
        <div className="obs-header">
          <PageHeader
            icon={Activity}
            title="Observability"
            description={
              <>
                Every stakeholder request as traced in Langfuse
                {state.mode === "mock" ? <span className="obs-amber"> (mock data)</span> : null}
              </>
            }
            actions={
              <>
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
              <a href={summary.host} target="_blank" rel="noreferrer" className="obs-button hidden lg:inline-flex">
                Langfuse
                <ExternalLink size={13} strokeWidth={1.75} aria-hidden />
              </a>
            ) : null}
              </>
            }
          />
        </div>
        {body}
        {traceId ? <TraceInspector traceId={traceId} onClose={close} supervisor={summary?.supervisor ?? null} /> : null}
      </div>
    </div>
  );
}
