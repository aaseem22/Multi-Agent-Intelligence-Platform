import { memo } from "react";
import type { ObsAgentStat, ObservabilitySummary } from "../types/observability";
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

function Bar({ value, max, format, alert }: { value: number | null; max: number; format: (v: number) => string; alert: boolean }) {
  const ratio = value == null || max <= 0 ? 0 : value / max;
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <div className="relative h-2 flex-1 bg-(--obs-line)/60">
        {/* Square at the baseline, 4px rounded data end. */}
        <div
          className="absolute inset-y-0 left-0 rounded-r-[4px]"
          style={{
            width: `${Math.max(ratio * 100, value ? 1.5 : 0)}%`,
            background: alert ? "var(--obs-alert)" : "var(--obs-ice-dim)",
            boxShadow: alert ? "0 0 8px rgba(255,93,82,0.45)" : "0 0 8px rgba(127,220,255,0.25)",
          }}
        />
      </div>
      <span className={`obs-mono w-16 shrink-0 text-right text-sm ${alert ? "obs-alert" : "obs-t1"}`}>
        {value == null ? "–" : format(value)}
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
    <Panel title="Per-agent readout" labelId="obs-agents" meta="bars scale to the busiest agent" className="obs-area-agents">
      {rows.length === 0 ? (
        <p className="obs-t3 text-sm">No agent runs in this window.</p>
      ) : (
        <div role="table" aria-labelledby="obs-agents" className="text-sm">
          <div role="row" className="hidden grid-cols-[150px_repeat(4,minmax(0,1fr))] gap-x-6 pb-2 md:grid">
            <span role="columnheader" className="obs-cond obs-t3 text-xs">Agent</span>
            {METRICS.map((m) => (
              <span key={m.key} role="columnheader" className="obs-cond obs-t3 text-xs">
                {m.label}
              </span>
            ))}
          </div>
          {rows.map((row) => (
            <div
              key={row.agent}
              role="row"
              className="grid grid-cols-2 gap-x-6 gap-y-2 border-t border-(--obs-line) py-2.5 md:grid-cols-[150px_repeat(4,minmax(0,1fr))] md:items-center"
            >
              <div role="rowheader" className="col-span-2 flex items-center gap-2.5 md:col-span-1">
                <span
                  aria-hidden
                  className="size-2.5 rounded-full"
                  style={{ background: agentHue(row.agent, summary.supervisor), boxShadow: `0 0 8px ${agentHue(row.agent, summary.supervisor)}` }}
                />
                <span className="obs-cond text-base font-semibold text-(--obs-text)">{agentName(row.agent)}</span>
                <span className="obs-t3 text-xs">{row.role === "supervisor" ? "supervisor" : ""}</span>
              </div>
              {METRICS.map((m) => (
                <div role="cell" key={m.key} className="min-w-0">
                  <span className="obs-cond obs-t3 mb-0.5 block text-xs md:hidden">{m.label}</span>
                  <Bar value={row[m.key]} max={max[m.key]} format={m.format} alert={m.key === "failures" && row.failures > 0} />
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
