import { useState } from "react";
import { evalsHref } from "../hooks/useHashRoute";
import { parseServerTime } from "../lib/format";
import type { RunSummary } from "../types/evals";
import { pct } from "./lib";
import { SectionHead } from "./ui";

const dateFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const MAX_RUNS = 10;

interface Point {
  run: RunSummary;
  x: number;
  rate: number;
  hat: number | null;
}

/**
 * Pass rate (solid) and pass^k (dashed) across completed runs, oldest to newest. Lines are SVG
 * stretched to the box with non-scaling strokes; labels and hit targets are HTML so text never scales.
 */
export function TrendChart({ runs }: { runs: RunSummary[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const series = runs
    .filter((run) => run.pass_rate !== null)
    .slice(0, MAX_RUNS)
    .reverse();

  if (series.length < 2) {
    return (
      <section className="card space-y-2 p-5" aria-labelledby="trend">
        <SectionHead id="trend" title="Across runs">
          The trend appears after a second completed run.
        </SectionHead>
      </section>
    );
  }

  const step = 100 / (series.length - 1);
  const points: Point[] = series.map((run, i) => ({ run, x: i * step, rate: run.pass_rate ?? 0, hat: run.config.trials > 1 ? run.pass_hat_k : null }));
  const y = (v: number) => 100 - v * 100;
  const line = (values: { x: number; v: number }[]) => values.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(2)},${y(p.v).toFixed(2)}`).join(" ");
  const ratePath = line(points.map((p) => ({ x: p.x, v: p.rate })));
  const hatPoints = points.filter((p) => p.hat !== null).map((p) => ({ x: p.x, v: p.hat as number }));
  const active = hover !== null ? points[hover] : null;

  return (
    <section className="card space-y-4 p-5" aria-labelledby="trend">
      <SectionHead
        id="trend"
        title="Across runs"
        actions={
          <p className="flex items-center gap-4 text-xs text-muted">
            <span className="inline-flex items-center gap-1.5">
              <span aria-hidden className="h-0.5 w-4 rounded-full bg-series-1" />
              Pass rate
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span aria-hidden className="w-4 border-t-2 border-dashed border-series-muted" />
              pass^k (runs with k of 2 or more)
            </span>
          </p>
        }
      >
        A capability score that climbs is progress; a regression score that dips is a break to investigate.
      </SectionHead>

      <div className="flex gap-3">
        <div aria-hidden className="relative w-8 shrink-0 text-right text-2xs text-faint">
          {[1, 0.5, 0].map((v) => (
            <span key={v} className="absolute right-0 -translate-y-1/2" style={{ top: `${y(v)}%` }}>
              {pct(v)}
            </span>
          ))}
        </div>
        <div className="relative h-44 min-w-0 flex-1">
          {[0, 0.5, 1].map((v) => (
            <span key={v} aria-hidden className="absolute inset-x-0 border-t border-line" style={{ top: `${y(v)}%` }} />
          ))}
          <svg aria-hidden className="absolute inset-0 h-full w-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none">
            {hatPoints.length > 1 ? (
              <path d={line(hatPoints)} fill="none" stroke="var(--color-series-muted)" strokeWidth={2} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
            ) : null}
            <path d={ratePath} fill="none" stroke="var(--color-series-1)" strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
          </svg>
          {points.map((p, i) => (
            <span key={p.run.run_id}>
              {p.hat !== null ? (
                <span
                  aria-hidden
                  className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-series-muted ring-2 ring-surface"
                  style={{ left: `${p.x}%`, top: `${y(p.hat)}%` }}
                />
              ) : null}
              <span
                aria-hidden
                className={`absolute -translate-x-1/2 -translate-y-1/2 rounded-full bg-series-1 ring-2 ring-surface transition-transform ${hover === i ? "size-3" : "size-2.5"}`}
                style={{ left: `${p.x}%`, top: `${y(p.rate)}%` }}
              />
              <a
                href={evalsHref({ kind: "run", runId: p.run.run_id })}
                aria-label={`${p.run.run_id}: pass rate ${pct(p.rate)}${p.hat !== null ? `, pass^${p.run.config.trials} ${pct(p.hat)}` : ""}`}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                className="absolute inset-y-0 -translate-x-1/2 rounded-md"
                style={{ left: `${p.x}%`, width: `${Math.max(step, 8)}%` }}
              />
            </span>
          ))}
          {active ? (
            <div
              role="status"
              className="pointer-events-none absolute z-10 w-max rounded-block border border-line bg-elevated px-3 py-2 text-xs shadow-raised"
              style={{
                left: `${active.x}%`,
                top: `${Math.min(y(active.rate), 60)}%`,
                transform: `translate(${active.x > 70 ? "calc(-100% - 12px)" : "12px"}, -50%)`,
              }}
            >
              <p className="font-mono text-2xs text-muted">{active.run.run_id}</p>
              <p className="mt-1 text-ink">
                Pass rate <span className="font-semibold tabular-nums">{pct(active.rate)}</span>
              </p>
              {active.hat !== null ? (
                <p className="text-ink">
                  pass^{active.run.config.trials} <span className="font-semibold tabular-nums">{pct(active.hat)}</span>
                </p>
              ) : null}
              <p className="text-muted">
                {active.run.tasks_total} tasks, k={active.run.config.trials}
              </p>
            </div>
          ) : null}
        </div>
      </div>
      <div aria-hidden className="relative ml-11 h-4 text-2xs text-faint">
        {points.map((p, i) => (
          <span
            key={p.run.run_id}
            className="absolute whitespace-nowrap"
            style={{ left: `${p.x}%`, transform: i === 0 ? "none" : i === points.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}
          >
            {dateFormat.format(parseServerTime(p.run.created_at))}
          </span>
        ))}
      </div>
    </section>
  );
}
