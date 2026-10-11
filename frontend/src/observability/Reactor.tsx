import { memo } from "react";
import type { ObservabilitySummary } from "../types/observability";
import { useCountUp } from "./hooks";
import { Panel } from "./Panel";
import { formatInt, formatPercent, formatSeconds, scoreLabel } from "./theme";

const SIZE = 240;
const C = SIZE / 2;
const STROKE = 12;
const RINGS = [
  { key: "success", r: 104, color: "var(--color-series-1)" },
  { key: "eval", r: 86, color: "var(--color-series-2)" },
  { key: "latency", r: 68, color: "var(--color-series-3)" },
] as const;

function Arc({ r, ratio, color }: { r: number; ratio: number; color: string }) {
  const length = 2 * Math.PI * r;
  const filled = Math.max(0, Math.min(ratio, 1)) * length;
  return (
    <>
      <circle cx={C} cy={C} r={r} fill="none" stroke="var(--color-subtle)" strokeWidth={STROKE} />
      {filled > 0.5 ? (
        <circle
          cx={C}
          cy={C}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeDasharray={`${filled.toFixed(1)} ${length.toFixed(1)}`}
          transform={`rotate(-90 ${C} ${C})`}
        />
      ) : null}
    </>
  );
}

function Marker({ r, ratio }: { r: number; ratio: number }) {
  const angle = Math.min(Math.max(ratio, 0), 1) * Math.PI * 2 - Math.PI / 2;
  const x1 = C + Math.cos(angle) * (r - STROKE / 2 - 2);
  const y1 = C + Math.sin(angle) * (r - STROKE / 2 - 2);
  const x2 = C + Math.cos(angle) * (r + STROKE / 2 + 2);
  const y2 = C + Math.sin(angle) * (r + STROKE / 2 + 2);
  return <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--color-ink)" strokeWidth={2} strokeLinecap="round" />;
}

function overallEvalRate(summary: ObservabilitySummary): number | null {
  const total = summary.scores.reduce((sum, s) => sum + s.count, 0);
  if (!total) return null;
  return summary.scores.reduce((sum, s) => sum + s.pass_rate * s.count, 0) / total;
}

function ReactorImpl({ summary }: { summary: ObservabilitySummary }) {
  const success = summary.success_rate ?? 0;
  const evalRate = overallEvalRate(summary);
  const target = summary.latency_target_ms ?? 45_000;
  const latencyRatio = summary.avg_latency_ms != null ? summary.avg_latency_ms / target : 0;
  const p95Ratio = summary.p95_latency_ms != null ? summary.p95_latency_ms / target : null;
  const overBudget = latencyRatio > 1;
  const latencyColor = overBudget ? "var(--color-warn)" : RINGS[2].color;

  const shownTraces = useCountUp(summary.traces);
  const shownSuccess = useCountUp(success * 1000) / 1000;
  const shownEval = useCountUp((evalRate ?? 0) * 1000) / 1000;
  const shownLatency = useCountUp(Math.min(latencyRatio, 1) * 1000) / 1000;
  const days = summary.window?.days ?? 7;

  const rows = [
    {
      label: "Answered cleanly",
      value: formatPercent(summary.success_rate),
      note: summary.success_rate == null ? "no traces" : "no failed agent or eval",
      color: RINGS[0].color,
    },
    {
      label: "Eval checks passed",
      value: formatPercent(evalRate),
      note: `${formatInt(summary.scores.reduce((s, x) => s + x.count, 0))} scores`,
      color: RINGS[1].color,
    },
    {
      label: "Average latency",
      value: formatSeconds(summary.avg_latency_ms),
      note: `${formatSeconds(target, 0)} target, p95 ${formatSeconds(summary.p95_latency_ms)}`,
      color: latencyColor,
    },
  ];

  return (
    <Panel title="Health" labelId="obs-core" meta={`Last ${days === 1 ? "24 hours" : `${days} days`}`} className="obs-area-reactor">
      <div className="relative mx-auto w-full max-w-[240px]">
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          className="block h-auto w-full"
          role="img"
          aria-label={`${summary.traces} traces. Success ${formatPercent(summary.success_rate)}, eval pass ${formatPercent(evalRate)}, average latency ${formatSeconds(summary.avg_latency_ms)} against a ${formatSeconds(target, 0)} target.`}
        >
          <Arc r={RINGS[0].r} ratio={shownSuccess} color={RINGS[0].color} />
          <Arc r={RINGS[1].r} ratio={shownEval} color={RINGS[1].color} />
          <Arc r={RINGS[2].r} ratio={shownLatency} color={latencyColor} />
          {p95Ratio != null ? <Marker r={RINGS[2].r} ratio={p95Ratio} /> : null}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="text-[2.5rem] leading-none font-semibold tracking-[-0.04em] text-ink">
            {formatInt(Math.round(shownTraces))}
          </span>
          <span className="mt-1 text-xs text-muted">traced requests</span>
        </div>
      </div>

      <ul className="mt-5 space-y-3">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center gap-3">
            <span aria-hidden className="h-8 w-1 shrink-0 rounded-full" style={{ background: row.color }} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink">{row.label}</p>
              <p className="text-2xs text-muted">{row.note}</p>
            </div>
            <span className="text-lg font-semibold tracking-tight text-ink tabular-nums">{row.value}</span>
          </li>
        ))}
      </ul>

      {summary.scores.length ? (
        <div className="mt-5 border-t border-line pt-4">
          <p className="mb-2.5 text-xs font-medium text-muted">Eval stages</p>
          <ul className="space-y-2">
            {summary.scores.map((score) => (
              <li key={score.name} className="grid grid-cols-[88px_1fr_44px] items-center gap-3">
                <span className="text-sm text-ink-2">{scoreLabel(score.name)}</span>
                <span className="relative h-1.5 rounded-full bg-subtle">
                  <span
                    className="absolute inset-y-0 left-0 rounded-full"
                    style={{
                      width: `${score.pass_rate * 100}%`,
                      background: score.pass_rate < 1 ? "var(--color-warn)" : RINGS[1].color,
                    }}
                  />
                </span>
                <span className="text-right text-xs font-medium text-ink tabular-nums" title={`${score.count} scores`}>
                  {formatPercent(score.pass_rate)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Panel>
  );
}

export const Reactor = memo(ReactorImpl);
