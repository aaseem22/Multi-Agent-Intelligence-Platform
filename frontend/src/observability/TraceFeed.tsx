import { memo } from "react";
import type { ObsScoreMark, ObsTraceItem, ObsTraceStatus } from "../types/observability";
import { AgentAvatar } from "../components/AgentName";
import { Panel } from "./Panel";
import { agentName, formatAgo, formatCompact, formatSeconds, scoreLabel } from "./theme";

const STATUS: Record<ObsTraceStatus, { label: string; className: string; dot: string }> = {
  ok: { label: "Answered", className: "bg-ok-soft text-ok", dot: "bg-ok" },
  partial: { label: "Partial", className: "bg-warn-soft text-warn", dot: "bg-warn" },
  error: { label: "Error", className: "bg-danger-soft text-danger", dot: "bg-danger" },
};

export function StatusMark({ status }: { status: ObsTraceStatus }) {
  const s = STATUS[status];
  return (
    <span className={`chip ${s.className}`}>
      <span aria-hidden className={`size-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

function EvalMarks({ scores }: { scores: ObsScoreMark[] }) {
  if (!scores.length) return null;
  const summary = scores.map((s) => `${scoreLabel(s.name)} ${s.passed}/${s.total}`).join(", ");
  return (
    <span className="inline-flex items-center gap-[3px]" title={`Eval: ${summary}`} aria-label={`Eval checks: ${summary}`}>
      {scores.map((s) => {
        const pass = s.passed === s.total;
        return (
          <span
            key={s.name}
            aria-hidden
            className="size-2 rounded-[3px]"
            style={{
              background: pass ? "var(--color-accent)" : "transparent",
              border: `1.5px solid ${pass ? "var(--color-accent)" : "var(--color-warn)"}`,
            }}
          />
        );
      })}
    </span>
  );
}

function TraceFeedImpl({
  traces,
  selectedId,
  onSelect,
  supervisor,
}: {
  traces: ObsTraceItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  supervisor: string | null;
}) {
  return (
    <Panel title="Recent requests" labelId="obs-feed" meta={`${traces.length} most recent`} className="obs-area-feed">
      {traces.length === 0 ? (
        <p className="text-sm text-muted">No traces in this window.</p>
      ) : (
        <ol className="obs-feed-list">
          {traces.map((trace) => (
            <li key={trace.id}>
              <button
                type="button"
                className="obs-feed-item"
                aria-current={trace.id === selectedId ? "true" : undefined}
                onClick={() => onSelect(trace.id)}
              >
                <span className="flex items-center justify-between gap-3">
                  <StatusMark status={trace.status} />
                  <time className="text-2xs text-faint" dateTime={trace.timestamp ?? undefined}>
                    {formatAgo(trace.timestamp)}
                  </time>
                </span>
                <span className="obs-question mt-1">{trace.question || "(no question recorded)"}</span>
                <span className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-xs">
                  <span className="font-medium text-ink tabular-nums">{formatSeconds(trace.latency_ms)}</span>
                  <span className="text-muted tabular-nums">{formatCompact(trace.tokens)} tokens</span>
                  {trace.agents.length > 0 ? (
                    <span className="flex -space-x-1">
                      {trace.agents.map((agent) => (
                        <span key={agent} className="rounded-[7px] ring-2 ring-surface" title={agentName(agent)}>
                          <AgentAvatar name={agent === supervisor ? "ceo" : agent} size="sm" />
                        </span>
                      ))}
                    </span>
                  ) : null}
                  {trace.peer_calls > 0 ? (
                    <span className="chip bg-accent-soft text-accent-strong" title={`${trace.peer_calls} peer calls`}>
                      {trace.peer_calls} peer
                    </span>
                  ) : null}
                  {trace.refusals > 0 ? (
                    <span className="chip bg-danger-soft text-danger" title={`${trace.refusals} peer calls refused`}>
                      {trace.refusals} refused
                    </span>
                  ) : null}
                  <span className="ml-auto">
                    <EvalMarks scores={trace.scores} />
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

export const TraceFeed = memo(TraceFeedImpl);
