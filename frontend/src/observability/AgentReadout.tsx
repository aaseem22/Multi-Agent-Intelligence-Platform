import { memo } from "react";
import type { ObsAgentStat, ObservabilitySummary } from "../types/observability";
import { AgentAvatar } from "../components/AgentName";
import { Panel } from "./Panel";
import { agentHue, agentName, formatInt, formatSeconds } from "./theme";

interface Metric {
  key: "runs" | "avg_latency_ms" | "tool_calls" | "failures";
  label: string;
  format: (value: number) => string;
}

const METRICS: Metric[] = [
  { key: "runs", label: "Runs", format: formatInt },
  { key: "avg_latency_ms", label: "Avg latency", format: (v) => formatSeconds(v) },
  { key: "tool_calls", label: "Tool calls", format: formatInt },
  { key: "failures", label: "Failures", format: formatInt },
];

function Bar({
  value,
  max,
  format,
  alert,
  color,
}: {
  value: number | null;
  max: number;
  format: (v: number) => string;
  alert: boolean;
  color: string;
}) {
  const ratio = value == null || max <= 0 ? 0 : value / max;
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <div className="relative h-1.5 flex-1 rounded-full bg-subtle">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            width: `${Math.max(ratio * 100, value ? 1.5 : 0)}%`,
            background: alert ? "var(--color-danger)" : color,
          }}
        />
      </div>
      <span className={`w-16 shrink-0 text-right text-sm font-medium tabular-nums ${alert ? "text-danger" : "text-ink"}`}>
        {value == null ? "-" : format(value)}
      </span>
    </div>
  );
}

function AgentReadoutImpl({ summary }: { summary: ObservabilitySummary }) {
  const rows: ObsAgentStat[] = summary.per_agent;
  const max = Object.fromEntries(
    METRICS.map((m) => [m.key, Math.max(0, ...rows.map((r) => r[m.key] ?? 0))]),
  ) as Record<Metric["key"], number>;

  return (
    <Panel title="Per-agent readout" labelId="obs-agents" meta="Bars scale to the busiest agent" className="obs-area-agents">
      {rows.length === 0 ? (
        <p className="text-sm text-muted">No agent runs in this window.</p>
      ) : (
        <div role="table" aria-labelledby="obs-agents" className="text-sm">
          <div role="row" className="hidden grid-cols-[150px_repeat(4,minmax(0,1fr))] gap-x-6 pb-2 md:grid">
            <span role="columnheader" className="text-xs text-muted">Agent</span>
            {METRICS.map((m) => (
              <span key={m.key} role="columnheader" className="text-xs text-muted">
                {m.label}
              </span>
            ))}
          </div>
          {rows.map((row) => (
            <div
              key={row.agent}
              role="row"
              className="grid grid-cols-2 gap-x-6 gap-y-2 border-t border-line py-3 md:grid-cols-[150px_repeat(4,minmax(0,1fr))] md:items-center"
            >
              <div role="rowheader" className="col-span-2 flex items-center gap-2.5 md:col-span-1">
                <AgentAvatar name={row.agent === summary.supervisor ? "ceo" : row.agent} size="sm" />
                <span className="text-base font-medium text-ink">{agentName(row.agent)}</span>
                {row.role === "supervisor" ? <span className="chip bg-subtle text-muted">Supervisor</span> : null}
              </div>
              {METRICS.map((m) => (
                <div role="cell" key={m.key} className="min-w-0">
                  <span className="mb-0.5 block text-xs text-muted md:hidden">{m.label}</span>
                  <Bar
                    value={row[m.key]}
                    max={max[m.key]}
                    format={m.format}
                    alert={m.key === "failures" && row.failures > 0}
                    color={agentHue(row.agent, summary.supervisor)}
                  />
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export const AgentReadout = memo(AgentReadoutImpl);
