import { memo } from "react";
import type { ObservabilitySummary } from "../types/observability";
import { useCountUp } from "./hooks";
import { Panel } from "./Panel";
import { formatInt, formatPercent, formatSeconds, scoreLabel } from "./theme";

const SIZE = 320;
const C = SIZE / 2;
const RINGS = [
  { key: "success", r: 128, color: "#7fdcff" },
  { key: "eval", r: 108, color: "#4fb3e0" },
  { key: "latency", r: 88, color: "#c4ecff" },
] as const;
const STROKE = 9;

const TICKS = Array.from({ length: 120 }, (_, i) => {
  const angle = (i / 120) * Math.PI * 2 - Math.PI / 2;
  const major = i % 10 === 0;
  const inner = 146 - (major ? 8 : 3);
  return {
    major,
    x1: +(C + Math.cos(angle) * inner).toFixed(2),
    y1: +(C + Math.sin(angle) * inner).toFixed(2),
    x2: +(C + Math.cos(angle) * 146).toFixed(2),
    y2: +(C + Math.sin(angle) * 146).toFixed(2),
  };
});

// Static chrome is hoisted so re-renders only touch the arcs and numbers.
const reactorChrome = (
  <g aria-hidden>
    <circle cx={C} cy={C} r={152} fill="none" stroke="var(--obs-line)" strokeWidth={1} />
    {TICKS.map((t, i) => (
      <line
        key={i}
        x1={t.x1}
        y1={t.y1}
        x2={t.x2}
        y2={t.y2}
        stroke={t.major ? "var(--obs-ice-dim)" : "var(--obs-line-strong)"}
        strokeWidth={t.major ? 1.5 : 1}
      />
    ))}
    <g className="obs-sweep">
      <circle cx={C} cy={C} r={150} fill="none" stroke="none" />
      <path d={`M ${C} ${C} L ${C} ${C - 150} A 150 150 0 0 1 ${C + 150 * Math.sin(0.5)} ${C - 150 * Math.cos(0.5)} Z`} fill="url(#obs-sweep-grad)" />
    </g>
    <circle cx={C} cy={C} r={70} fill="url(#obs-core-grad)" className="obs-breathe" />
    <circle cx={C} cy={C} r={70} fill="none" stroke="var(--obs-line-strong)" strokeWidth={1} strokeDasharray="2 4" />
  </g>
);

function Arc({ r, ratio, color }: { r: number; ratio: number; color: string }) {
  const length = 2 * Math.PI * r;
  const filled = Math.max(0, Math.min(ratio, 1)) * length;
  return (
    <>
      <circle cx={C} cy={C} r={r} fill="none" stroke="var(--obs-line)" strokeWidth={STROKE} />
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
          style={{ filter: `drop-shadow(0 0 5px ${color}66)` }}
        />
      ) : null}
    </>
  );
}

function Marker({ r, ratio, color }: { r: number; ratio: number; color: string }) {
  const angle = Math.min(Math.max(ratio, 0), 1) * Math.PI * 2 - Math.PI / 2;
  const x1 = C + Math.cos(angle) * (r - STROKE);
  const y1 = C + Math.sin(angle) * (r - STROKE);
  const x2 = C + Math.cos(angle) * (r + STROKE);
  const y2 = C + Math.sin(angle) * (r + STROKE);
  return <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={2} strokeLinecap="round" />;
}

/** A tiny three-ring glyph that lights the ring a legend row describes: identity by position. */
function RingGlyph({ index, color }: { index: number; color: string }) {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden className="shrink-0">
      {[10, 7, 4].map((r, i) => (
        <circle
          key={r}
          cx="11"
          cy="11"
          r={r}
          fill="none"
          stroke={i === index ? color : "var(--obs-line-strong)"}
          strokeWidth={i === index ? 2.2 : 1}
        />
      ))}
    </svg>
  );
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
  const latencyColor = overBudget ? "var(--obs-amber)" : RINGS[2].color;

  const shownTraces = useCountUp(summary.traces);
  const shownSuccess = useCountUp(success * 1000) / 1000;
  const shownEval = useCountUp((evalRate ?? 0) * 1000) / 1000;
  const shownLatency = useCountUp(Math.min(latencyRatio, 1) * 1000) / 1000;
  const days = summary.window?.days ?? 7;

  const rows = [
    {
      label: "Requests answered cleanly",
      value: formatPercent(summary.success_rate),
      note: summary.success_rate == null ? "no traces" : "no failed agent, no failed eval",
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
      note: `of ${formatSeconds(target, 0)} budget, p95 ${formatSeconds(summary.p95_latency_ms)}`,
      color: latencyColor,
    },
  ];

  return (
    <Panel title="Core" labelId="obs-core" meta={`last ${days === 1 ? "24 hours" : `${days} days`}`} className="obs-area-reactor">
      <div className="relative mx-auto w-full max-w-[320px]">
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          className="block h-auto w-full"
          role="img"
          aria-label={`${summary.traces} traces. Success ${formatPercent(summary.success_rate)}, eval pass ${formatPercent(evalRate)}, average latency ${formatSeconds(summary.avg_latency_ms)} against a ${formatSeconds(target, 0)} budget.`}
        >
          <defs>
            <radialGradient id="obs-core-grad">
              <stop offset="0%" stopColor="rgba(127,220,255,0.22)" />
              <stop offset="70%" stopColor="rgba(127,220,255,0.04)" />
              <stop offset="100%" stopColor="rgba(127,220,255,0)" />
            </radialGradient>
            <linearGradient id="obs-sweep-grad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="rgba(127,220,255,0)" />
              <stop offset="100%" stopColor="rgba(127,220,255,0.14)" />
            </linearGradient>
          </defs>
          {reactorChrome}
          <Arc r={RINGS[0].r} ratio={shownSuccess} color={RINGS[0].color} />
          <Arc r={RINGS[1].r} ratio={shownEval} color={RINGS[1].color} />
          <Arc r={RINGS[2].r} ratio={shownLatency} color={latencyColor} />
          {p95Ratio != null ? <Marker r={RINGS[2].r} ratio={p95Ratio} color="var(--obs-text-2)" /> : null}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="obs-cond text-[3.5rem] leading-none font-light tracking-tight text-(--obs-text)" style={{ textShadow: "0 0 18px rgba(127,220,255,0.45)" }}>
            {formatInt(Math.round(shownTraces))}
          </span>
          <span className="obs-cond mt-1 text-sm text-(--obs-text-2)">traces</span>
        </div>
      </div>

      <ul className="mt-3 space-y-2.5">
        {rows.map((row, i) => (
          <li key={row.label} className="flex items-center gap-3">
            <RingGlyph index={i} color={row.color} />
            <div className="min-w-0 flex-1">
              <p className="obs-cond text-sm text-(--obs-text-2)">{row.label}</p>
              <p className="obs-mono text-2xs text-(--obs-text-3)">{row.note}</p>
            </div>
            <span className="obs-mono text-lg text-(--obs-text)">{row.value}</span>
          </li>
        ))}
      </ul>

      {summary.scores.length ? (
        <div className="mt-4 border-t border-(--obs-line) pt-3">
          <p className="obs-cond mb-2 text-xs text-(--obs-text-3)">Eval stages</p>
          <ul className="space-y-1.5">
            {summary.scores.map((score) => (
              <li key={score.name} className="grid grid-cols-[84px_1fr_48px] items-center gap-3">
                <span className="obs-cond text-sm text-(--obs-text-2)">{scoreLabel(score.name)}</span>
                <span className="relative h-1 rounded-full bg-(--obs-line)">
                  <span
                    className="absolute inset-y-0 left-0 rounded-full"
                    style={{
                      width: `${score.pass_rate * 100}%`,
                      background: score.pass_rate < 1 ? "var(--obs-amber)" : "var(--obs-ice-dim)",
                    }}
                  />
                </span>
                <span className="obs-mono text-right text-xs text-(--obs-text)" title={`${score.count} scores`}>
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
