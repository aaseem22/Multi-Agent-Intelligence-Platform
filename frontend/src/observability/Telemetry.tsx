import { memo, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { ObsBucket, ObservabilitySummary } from "../types/observability";
import { useCountUp } from "./hooks";
import { Panel } from "./Panel";
import { formatBucket, formatCompact, formatCost, formatInt, formatPercent, formatSeconds } from "./theme";

const CHART_H = 104;
const PAD = { top: 16, right: 10, bottom: 18, left: 4 };

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

interface SeriesSpec {
  key: "traces" | "avg_latency_ms" | "tokens";
  title: string;
  headline: string;
  format: (value: number) => string;
  area: boolean;
  reference?: { value: number; label: string };
}

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const exponent = Math.pow(10, Math.floor(Math.log10(value)));
  const fraction = value / exponent;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10;
  return nice * exponent;
}

function SparkChart({
  spec,
  buckets,
  bucketKind,
  hover,
  onHover,
}: {
  spec: SeriesSpec;
  buckets: ObsBucket[];
  bucketKind: "hour" | "day";
  hover: number | null;
  onHover: (index: number | null) => void;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const values = buckets.map((b) => b[spec.key]);
  const max = niceMax(Math.max(0, ...values.map((v) => v ?? 0), spec.reference?.value ?? 0));
  const innerW = Math.max(width - PAD.left - PAD.right, 1);
  const innerH = CHART_H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (buckets.length <= 1 ? innerW / 2 : (i / (buckets.length - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - (v / max) * innerH;
  const baseline = PAD.top + innerH;

  // Line segments break across empty (null) buckets rather than inventing values.
  const segments: [number, number][][] = [];
  let current: [number, number][] = [];
  values.forEach((v, i) => {
    if (v == null) {
      if (current.length) segments.push(current);
      current = [];
    } else current.push([x(i), y(v)]);
  });
  if (current.length) segments.push(current);
  const f = (n: number) => n.toFixed(1);
  const linePaths = segments.map((seg) => seg.map(([px, py], i) => `${i ? "L" : "M"} ${f(px)} ${f(py)}`).join(" "));
  const areaPaths = spec.area
    ? segments.map(
        (seg) =>
          `M ${f(seg[0][0])} ${f(baseline)} ` +
          seg.map(([px, py]) => `L ${f(px)} ${f(py)}`).join(" ") +
          ` L ${f(seg[seg.length - 1][0])} ${f(baseline)} Z`,
      )
    : [];

  let lastIndex = -1;
  values.forEach((v, i) => {
    if (v != null) lastIndex = i;
  });

  const onMove = (event: ReactPointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    const index = Math.round(ratio * (buckets.length - 1));
    onHover(Math.max(0, Math.min(buckets.length - 1, index)));
  };

  const hoverValue = hover != null ? values[hover] : null;

  return (
    <figure className="min-w-0">
      <figcaption className="flex items-baseline justify-between gap-2">
        <span className="text-sm text-muted">{spec.title}</span>
        <span className="text-base font-semibold text-ink tabular-nums">
          {hover != null ? (hoverValue == null ? "-" : spec.format(hoverValue)) : spec.headline}
        </span>
      </figcaption>
      <div ref={ref} className="relative mt-1">
        {width > 0 ? (
          <svg width={width} height={CHART_H} className="block" aria-hidden>
            <line x1={PAD.left} x2={width - PAD.right} y1={PAD.top} y2={PAD.top} stroke="var(--obs-line)" strokeWidth={1} />
            <text x={PAD.left} y={PAD.top - 5} fontSize={11} fill="var(--obs-text-3)" className="obs-mono">
              {spec.format(max)}
            </text>
            {spec.reference ? (
              <g>
                <line
                  x1={PAD.left}
                  x2={width - PAD.right}
                  y1={y(spec.reference.value)}
                  y2={y(spec.reference.value)}
                  stroke="var(--obs-amber)"
                  strokeOpacity={0.55}
                  strokeWidth={1}
                />
                <text x={PAD.left + 2} y={y(spec.reference.value) - 4} fontSize={11} fill="var(--obs-amber)" className="obs-cond">
                  {spec.reference.label}
                </text>
              </g>
            ) : null}
            {areaPaths.map((d, i) => (
              <path key={`a${i}`} d={d} fill="var(--obs-ice)" fillOpacity={0.08} />
            ))}
            {linePaths.map((d, i) => (
              <path key={`l${i}`} d={d} fill="none" stroke="var(--obs-ice)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {segments
              .filter((seg) => seg.length === 1)
              .map((seg, i) => (
                <circle key={`s${i}`} cx={seg[0][0]} cy={seg[0][1]} r={3} fill="var(--obs-ice)" />
              ))}
            <line x1={PAD.left} x2={width - PAD.right} y1={baseline} y2={baseline} stroke="var(--obs-line-strong)" strokeWidth={1} />
            {lastIndex >= 0 && hover == null ? (
              <circle cx={x(lastIndex)} cy={y(values[lastIndex] ?? 0)} r={4} fill="var(--obs-ice)" stroke="var(--obs-panel)" strokeWidth={2} />
            ) : null}
            {hover != null ? (
              <g>
                <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={baseline} stroke="var(--obs-text-3)" strokeWidth={1} />
                {hoverValue != null ? (
                  <circle cx={x(hover)} cy={y(hoverValue)} r={4.5} fill="var(--obs-ice)" stroke="var(--obs-panel)" strokeWidth={2} />
                ) : null}
              </g>
            ) : null}
            {buckets.length ? (
              <>
                <text x={PAD.left} y={CHART_H - 3} fontSize={11} fill="var(--obs-text-3)" className="obs-mono">
                  {formatBucket(buckets[0].bucket, bucketKind)}
                </text>
                <text x={width - PAD.right} y={CHART_H - 3} fontSize={11} textAnchor="end" fill="var(--obs-text-3)" className="obs-mono">
                  {formatBucket(buckets[buckets.length - 1].bucket, bucketKind)}
                </text>
              </>
            ) : null}
            <rect
              x={PAD.left}
              y={0}
              width={innerW}
              height={CHART_H}
              fill="transparent"
              onPointerMove={onMove}
              onPointerDown={onMove}
              onPointerLeave={() => onHover(null)}
            />
          </svg>
        ) : (
          <div style={{ height: CHART_H }} />
        )}
        {hover != null && width > 0 ? (
          <div
            className="obs-tooltip"
            style={{
              left: Math.min(Math.max(x(hover), 70), width - 70),
              top: 0,
              transform: "translate(-50%, -100%)",
            }}
          >
            <p className="obs-mono text-xs obs-t3">{formatBucket(buckets[hover].bucket, bucketKind)}</p>
            <p className="obs-mono">
              {hoverValue == null ? "no traces" : spec.format(hoverValue)}
              <span className="obs-cond obs-t2"> {spec.title.toLowerCase()}</span>
            </p>
          </div>
        ) : null}
      </div>
    </figure>
  );
}

function Readout({ label, value, format, tone }: { label: string; value: number; format: (v: number) => string; tone?: "amber" | "alert" }) {
  const shown = useCountUp(value);
  return (
    <div className="obs-readout">
      <p className={`obs-readout-value ${tone === "alert" ? "obs-alert" : tone === "amber" ? "obs-amber" : ""}`}>
        {format(shown)}
      </p>
      <p className="obs-readout-label">{label}</p>
    </div>
  );
}

function TelemetryImpl({ summary }: { summary: ObservabilitySummary }) {
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const buckets = summary.timeseries;
  const bucketKind = summary.window?.bucket ?? "day";
  const target = summary.latency_target_ms ?? undefined;

  const specs: SeriesSpec[] = [
    {
      key: "traces",
      title: bucketKind === "hour" ? "Traces per hour" : "Traces per day",
      headline: `${formatInt(summary.traces)} total`,
      format: (v) => formatInt(v),
      area: true,
    },
    {
      key: "avg_latency_ms",
      title: "Average latency",
      headline: formatSeconds(summary.avg_latency_ms),
      format: (v) => formatSeconds(v, v >= 10_000 ? 0 : 1),
      area: false,
      reference: target ? { value: target, label: "budget" } : undefined,
    },
    {
      key: "tokens",
      title: "Tokens",
      headline: `${formatCompact(summary.total_tokens)} total`,
      format: (v) => formatCompact(Math.round(v)),
      area: true,
    },
  ];

  return (
    <Panel
      title="Telemetry"
      labelId="obs-telemetry"
      className="obs-area-telemetry"
      meta={
        <button type="button" className="obs-button h-7! text-xs!" aria-pressed={showTable} onClick={() => setShowTable((v) => !v)}>
          {showTable ? "Show charts" : "Show table"}
        </button>
      }
    >
      {showTable ? (
        <div className="max-h-[260px] overflow-auto">
          <table className="obs-mono w-full text-left text-xs">
            <caption className="sr-only">Traces, average latency and tokens per {bucketKind}</caption>
            <thead className="obs-t3">
              <tr>
                <th className="py-1 pr-3 font-normal">{bucketKind === "hour" ? "Hour" : "Day"}</th>
                <th className="py-1 pr-3 text-right font-normal">Traces</th>
                <th className="py-1 pr-3 text-right font-normal">Avg latency</th>
                <th className="py-1 text-right font-normal">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => (
                <tr key={b.bucket} className="border-t border-line">
                  <td className="py-1 pr-3 obs-t2">{formatBucket(b.bucket, bucketKind)}</td>
                  <td className="py-1 pr-3 text-right">{formatInt(b.traces)}</td>
                  <td className="py-1 pr-3 text-right">{formatSeconds(b.avg_latency_ms)}</td>
                  <td className="py-1 text-right">{formatInt(b.tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-x-8 gap-y-5 pt-3 md:grid-cols-3">
          {specs.map((spec) => (
            <SparkChart key={spec.key} spec={spec} buckets={buckets} bucketKind={bucketKind} hover={hover} onHover={setHover} />
          ))}
        </div>
      )}

      <div className="obs-readouts">
        <Readout label="Tokens" value={summary.total_tokens} format={(v) => formatCompact(Math.round(v))} />
        <Readout label="Cost" value={summary.total_cost} format={formatCost} />
        <Readout label="LLM calls" value={summary.llm_calls} format={(v) => formatInt(v)} />
        <Readout label="Tool calls" value={summary.tool_calls} format={(v) => formatInt(v)} />
        <Readout label="Peer calls" value={summary.peer_calls} format={(v) => formatInt(v)} />
        <Readout label="Refused peer calls" value={summary.refusals} format={(v) => formatInt(v)} tone={summary.refusals > 0 ? "amber" : undefined} />
        <Readout label="Error rate" value={summary.error_rate} format={(v) => formatPercent(v, 1)} tone={summary.error_rate > 0 ? "alert" : undefined} />
      </div>
    </Panel>
  );
}

export const Telemetry = memo(TelemetryImpl);
