import { memo } from "react";
import type { ObsScoreMark, ObsTraceItem, ObsTraceStatus } from "../types/observability";
import { Panel } from "./Panel";
import { agentHue, agentName, formatAgo, formatCompact, formatSeconds, scoreLabel } from "./theme";

const STATUS: Record<ObsTraceStatus, { glyph: string; label: string; className: string }> = {
  ok: { glyph: "●", label: "Answered", className: "obs-ok" },
  partial: { glyph: "◐", label: "Partial", className: "obs-amber" },
  error: { glyph: "✕", label: "Error", className: "obs-alert" },
};

export function StatusMark({ status }: { status: ObsTraceStatus }) {
  const s = STATUS[status];
  return (
    <span className={`obs-cond inline-flex items-center gap-1 text-xs ${s.className}`}>
      <span aria-hidden>{s.glyph}</span>
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
            className="size-[7px]"
            style={{
              background: pass ? "var(--obs-ice-dim)" : "transparent",
              border: `1px solid ${pass ? "var(--obs-ice-dim)" : "var(--obs-amber)"}`,
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
    <Panel title="Trace feed" labelId="obs-feed" meta={`${traces.length} most recent`} className="obs-area-feed">
      {traces.length === 0 ? (
        <p className="obs-t3 text-sm">No traces in this window.</p>
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
                  <time className="obs-mono obs-t3 text-2xs" dateTime={trace.timestamp ?? undefined}>
                    {formatAgo(trace.timestamp)}
                  </time>
                </span>
                <span className="obs-question mt-1">{trace.question || "(no question recorded)"}</span>
                <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                  <span className="obs-mono obs-t1">{formatSeconds(trace.latency_ms)}</span>
                  <span className="obs-mono obs-t2">{formatCompact(trace.tokens)} tok</span>
                  <span className="inline-flex items-center gap-2">
                    {trace.agents.map((agent) => (
                      <span key={agent} className="obs-cond inline-flex items-center gap-1 obs-t2">
                        <span aria-hidden className="size-1.5 rounded-full" style={{ background: agentHue(agent, supervisor) }} />
                        {agentName(agent)}
                      </span>
                    ))}
                  </span>
                  {trace.peer_calls > 0 ? (
                    <span className="obs-mono obs-ice" title={`${trace.peer_calls} peer calls`}>
                      ⇄ {trace.peer_calls}
                    </span>
                  ) : null}
                  {trace.refusals > 0 ? (
                    <span className="obs-mono obs-alert" title={`${trace.refusals} peer calls refused`}>
                      ⊘ {trace.refusals}
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
