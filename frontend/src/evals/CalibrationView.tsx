import { Scale } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { evalsHref } from "../hooks/useHashRoute";
import type { CalibrationStats } from "../types/evals";
import { humanise, pct, useEvals } from "./lib";
import { Figure, Meter, SectionHead } from "./ui";

const TRUST_THRESHOLD = 20;

function Split({ stats }: { stats: CalibrationStats }) {
  const agreed = Math.max(0, stats.labels - stats.judge_false_pass - stats.judge_false_fail);
  const parts = [
    { key: "agreed", label: "Judge and you agree", n: agreed, fill: "bg-ink-2" },
    { key: "fp", label: "False pass: judge passed, you failed", n: stats.judge_false_pass, fill: "bg-danger" },
    { key: "ff", label: "False fail: judge failed, you passed", n: stats.judge_false_fail, fill: "bg-warn" },
  ];
  return (
    <figure className="space-y-3">
      <div aria-hidden className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-subtle">
        {parts
          .filter((p) => p.n > 0)
          .map((p) => (
            <span key={p.key} className={`h-full ${p.fill}`} style={{ width: `${(p.n / Math.max(stats.labels, 1)) * 100}%` }} />
          ))}
      </div>
      <figcaption>
        <ul className="grid gap-2 sm:grid-cols-3">
          {parts.map((p) => (
            <li key={p.key} className="flex items-start gap-2 text-sm">
              <span aria-hidden className={`mt-1.5 size-2 shrink-0 rounded-full ${p.fill}`} />
              <span>
                <span className="font-semibold text-ink tabular-nums">{p.n}</span> <span className="text-ink-2">{p.label}</span>
              </span>
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}

export function CalibrationView() {
  const [stats, reload] = useEvals((client, signal) => client.getCalibration(signal), "evals-calibration");

  if (stats.status === "loading" && !stats.data) {
    return (
      <div className="card p-6">
        <LoadingState label="Loading calibration" lines={4} />
      </div>
    );
  }
  if (stats.status === "error" && !stats.data) return <ErrorState title="Could not load calibration" detail={stats.error} onRetry={reload} />;
  const s = stats.data as CalibrationStats;
  const enough = s.labels >= TRUST_THRESHOLD;

  return (
    <div className="space-y-5">
      <section className="card space-y-5 p-5 sm:p-6" aria-labelledby="calibration">
        <SectionHead id="calibration" title="Is the judge trustworthy?">
          A model grader is only useful if it agrees with a careful human. Open a trial, read the answer, and mark each model grader Agree or Disagree. These labels never change scores; they measure the judge.
        </SectionHead>
        {s.labels === 0 ? (
          <EmptyState title="No human labels yet" icon={<Scale size={20} strokeWidth={1.75} />}>
            Open any trial from a run and use Agree or Disagree under each model grader.{" "}
            <a href={evalsHref({ kind: "runs" })} className="link">
              Go to runs
            </a>
          </EmptyState>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
              <Figure value={pct(s.agreement)} label="Agreement" note="Labels where judge and human match" />
              <Figure value={String(s.labels)} label="Labels" note="Across all runs" />
              <Figure value={String(s.judge_false_pass)} label="False passes" note="The risky kind: bad answers let through" />
              <Figure value={String(s.judge_false_fail)} label="False fails" note="Good answers penalised" />
            </div>
            <Split stats={s} />
          </>
        )}
        <div className={`rounded-block px-4 py-3 text-sm ${enough ? "bg-subtle text-ink-2" : "border border-warn/25 bg-warn-soft text-ink-2"}`}>
          <p className="font-medium text-ink">
            {enough ? `${s.labels} labels: enough to start trusting the agreement figure.` : `Label at least ~${TRUST_THRESHOLD} trials before trusting the judge. ${s.labels} so far.`}
          </p>
          <p className="mt-1">
            Pick a mix: trials the judge passed and failed, from both suites. Aim for agreement above 85% with few false passes; if it is lower, tighten the rubric or give the judge more context before
            relying on model-graded scores.
          </p>
          {!enough ? (
            <div className="mt-3 max-w-sm">
              <Meter value={s.labels / TRUST_THRESHOLD} tone="bg-warn" label="Labels towards the threshold" />
            </div>
          ) : null}
        </div>
      </section>

      {Object.keys(s.by_grader).length > 0 ? (
        <section className="card space-y-4 p-5" aria-labelledby="by-grader">
          <SectionHead id="by-grader" title="Agreement by model grader">
            Each rubric is calibrated separately; one weak rubric can hide behind a good average.
          </SectionHead>
          <ul className="space-y-3.5">
            {Object.entries(s.by_grader)
              .sort((a, b) => a[1] - b[1])
              .map(([name, value]) => (
                <li key={name} className="grid grid-cols-[minmax(0,1fr)_3rem] items-center gap-x-4 gap-y-1.5">
                  <p className="truncate text-sm text-ink">{humanise(name)}</p>
                  <p className="row-span-2 text-right text-sm font-medium text-ink tabular-nums">{pct(value)}</p>
                  <Meter value={value} target={0.85} label={`${name} agreement`} tone={value < 0.85 ? "bg-warn" : "bg-ink-2"} />
                </li>
              ))}
          </ul>
          <p className="text-xs text-muted">The tick marks 85%, a reasonable bar for relying on a judge.</p>
        </section>
      ) : null}
    </div>
  );
}
