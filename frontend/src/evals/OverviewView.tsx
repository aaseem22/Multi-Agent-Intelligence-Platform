import { ArrowRight, FlaskConical } from "lucide-react";
import { useMemo } from "react";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { evalsHref } from "../hooks/useHashRoute";
import { formatRelative } from "../lib/format";
import type { GraderKind, RunSummary } from "../types/evals";
import { ConsistencyBand } from "./ConsistencyBand";
import { graderKinds, humanise, isActive, kindOf, KIND_COPY, latestCompleted, pct, fmtScore, SUITE_COPY, useEvals } from "./lib";
import { TrendChart } from "./TrendChart";
import { Figure, Meter, SectionHead } from "./ui";

function ActiveRunStrip({ run }: { run: RunSummary }) {
  return (
    <a
      href={evalsHref({ kind: "runs" })}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-block border border-accent/25 bg-accent-soft px-4 py-2.5 text-sm text-accent-strong transition-colors hover:border-accent/50"
    >
      <span aria-hidden className="live-dot" />
      <span className="font-medium">Run {run.run_id} is in progress</span>
      <span>
        {run.trials_done} of {run.trials_total} trials graded
      </span>
      <span className="ml-auto inline-flex items-center gap-1 font-medium">
        Follow progress
        <ArrowRight aria-hidden size={14} strokeWidth={1.75} />
      </span>
    </a>
  );
}

function FirstRun() {
  return (
    <div className="card">
      <EmptyState title="No completed eval runs yet" icon={<FlaskConical size={20} strokeWidth={1.75} />}>
        <p>
          Start one from the Runs tab, or from a terminal in <code className="font-mono text-xs">backend/</code>:
        </p>
        <pre className="mt-3 rounded-block bg-subtle px-3 py-2 text-left font-mono text-2xs whitespace-pre-wrap break-words text-ink-2">
          uv run python -m app.evals.run --dataset golden --trials 1
        </pre>
        <p className="mt-3">A first pass over the golden dataset with one trial takes about half an hour on the Gemini free tier.</p>
        <a href={evalsHref({ kind: "runs" })} className="btn btn-primary mt-4">
          Set up a run
        </a>
      </EmptyState>
    </div>
  );
}

function Headline({ run }: { run: RunSummary }) {
  const k = run.config.trials;
  const passedTasks = run.tasks.filter((t) => t.pass_at_k).length;
  const steadyTasks = run.tasks.filter((t) => t.pass_hat_k).length;
  return (
    <section aria-labelledby="latest-run" className="card overflow-hidden">
      <div className="grid gap-x-10 gap-y-6 p-5 sm:p-6 lg:grid-cols-[minmax(0,1fr)_16rem]">
        <div className="min-w-0 space-y-5">
          <div>
            <h2 id="latest-run" className="text-sm text-muted">
              Latest completed run,{" "}
              <a href={evalsHref({ kind: "run", runId: run.run_id })} className="link font-mono text-xs">
                {run.run_id}
              </a>{" "}
              {run.finished_at ? formatRelative(run.finished_at) : ""}
            </h2>
            <p className="mt-2 max-w-[60ch] text-xl leading-snug font-semibold tracking-tight text-ink">
              {k > 1
                ? `${passedTasks} of ${run.tasks_total} tasks passed at least once in ${k} trials. ${steadyTasks} passed every time.`
                : `${passedTasks} of ${run.tasks_total} tasks passed on a single trial each.`}
            </p>
          </div>
          <ConsistencyBand passRate={run.pass_rate} passAtK={run.pass_at_k} passHatK={run.pass_hat_k} k={k} />
          <div className="grid grid-cols-2 gap-x-6 gap-y-5 border-t border-line pt-5 sm:grid-cols-4">
            <Figure value={pct(run.pass_rate)} label="Pass rate" note="Share of all trials that passed" />
            <Figure value={pct(run.pass_at_k)} label={`pass@${k}`} note="Tasks with at least one pass" />
            <Figure value={pct(run.pass_hat_k)} label={`pass^${k}`} note="Tasks that passed every trial" />
            <Figure value={fmtScore(run.mean_score)} label="Mean score" note="Weighted grader score, 0 to 1" />
          </div>
        </div>
        <dl className="space-y-3 border-line text-sm lg:border-l lg:pl-6">
          {[
            ["Agent model", run.agent_model],
            ["CEO model", run.ceo_model],
            ["Judge model", run.config.judge_enabled ? run.judge_model : "Judge off for this run"],
            ["Dataset", `${run.config.dataset} v${run.dataset_version}`],
            ["Trials per task", String(k)],
            ["Live recovery", run.config.self_eval_recovery === "retry" ? "Retry with reviewer feedback" : "Observe only"],
          ].map(([term, value]) => (
            <div key={term}>
              <dt className="text-xs text-muted">{term}</dt>
              <dd className="mt-0.5 font-mono text-xs break-all text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

function RateRows({ rows }: { rows: { key: string; label: string; note?: string; value: number; target?: number }[] }) {
  if (rows.length === 0) return <p className="text-sm text-muted">Nothing graded yet.</p>;
  return (
    <ul className="space-y-3.5">
      {rows.map((row) => (
        <li key={row.key} className="grid grid-cols-[minmax(0,1fr)_3rem] items-center gap-x-4 gap-y-1.5">
          <div className="min-w-0">
            <p className="truncate text-sm text-ink">{row.label}</p>
            {row.note ? <p className="text-xs text-muted">{row.note}</p> : null}
          </div>
          <p className="row-span-2 text-right text-sm font-medium text-ink tabular-nums">{pct(row.value)}</p>
          <Meter value={row.value} target={row.target} label={`${row.label} pass rate`} tone={row.value < 0.5 ? "bg-danger" : "bg-ink-2"} />
        </li>
      ))}
    </ul>
  );
}

function Suites({ run }: { run: RunSummary }) {
  const rows = (["regression", "capability"] as const)
    .filter((suite) => run.by_suite[suite] !== undefined)
    .map((suite) => ({
      key: suite,
      label: SUITE_COPY[suite].label,
      note: SUITE_COPY[suite].line,
      value: run.by_suite[suite],
      target: suite === "regression" ? 1 : undefined,
    }));
  return (
    <section className="card space-y-4 p-5" aria-labelledby="by-suite">
      <SectionHead id="by-suite" title="By suite">
        Capability and regression evals answer different questions, so they are read separately.
      </SectionHead>
      <RateRows rows={rows} />
    </section>
  );
}

function Categories({ run }: { run: RunSummary }) {
  const rows = Object.entries(run.by_category)
    .sort((a, b) => a[1] - b[1])
    .map(([key, value]) => ({ key, label: humanise(key), value }));
  return (
    <section className="card space-y-4 p-5" aria-labelledby="by-category">
      <SectionHead id="by-category" title="By category">
        Weakest first.
      </SectionHead>
      <RateRows rows={rows} />
    </section>
  );
}

function Graders({ run, kinds }: { run: RunSummary; kinds: Map<string, GraderKind> }) {
  const groups = new Map<GraderKind, { key: string; label: string; value: number }[]>();
  for (const [name, value] of Object.entries(run.grader_pass_rates)) {
    const kind = kindOf(name, kinds);
    groups.set(kind, [...(groups.get(kind) ?? []), { key: name, label: humanise(name), value }]);
  }
  const order: GraderKind[] = ["code", "model", "human"];
  return (
    <section className="card space-y-5 p-5" aria-labelledby="graders">
      <SectionHead id="graders" title="Graders">
        How often each check passed across all trials. A grader that almost never passes is often a broken task or an over-strict check, so read a few transcripts before trusting it.
      </SectionHead>
      <div className="grid gap-x-10 gap-y-6 md:grid-cols-2">
        {order
          .filter((kind) => groups.has(kind))
          .map((kind) => (
            <div key={kind} className="space-y-3">
              <div>
                <h3 className="text-sm font-semibold text-ink">{KIND_COPY[kind].label}</h3>
                <p className="text-xs text-muted">{kind === "model" ? `${KIND_COPY.model.line} Judge: ${run.judge_model}.` : KIND_COPY[kind].line}</p>
              </div>
              <RateRows rows={(groups.get(kind) ?? []).sort((a, b) => a.value - b.value)} />
            </div>
          ))}
      </div>
    </section>
  );
}

export function OverviewView() {
  const [runs, reload] = useEvals((client, signal) => client.getRuns(signal), "evals-runs");
  const latest = runs.data ? latestCompleted(runs.data) : null;
  const latestId = latest?.run_id ?? "none";
  const [trials] = useEvals((client, signal) => (latest ? client.getTrials(latest.run_id, signal) : Promise.resolve([])), `evals-trials-${latestId}`);
  const kinds = useMemo(() => graderKinds(trials.data ?? []), [trials.data]);

  if (runs.status === "loading" && !runs.data) {
    return (
      <div className="card p-6">
        <LoadingState label="Loading eval runs" lines={5} />
      </div>
    );
  }
  if (runs.status === "error" && !runs.data) return <ErrorState title="Could not load eval runs" detail={runs.error} onRetry={reload} />;

  const list = runs.data ?? [];
  const active = list.find((run) => isActive(run.status));
  const completed = list.filter((run) => run.status === "completed");

  return (
    <div className="space-y-5">
      {active ? <ActiveRunStrip run={active} /> : null}
      {latest ? (
        <>
          <Headline run={latest} />
          <div className="grid gap-5 lg:grid-cols-2">
            <Suites run={latest} />
            <Categories run={latest} />
          </div>
          <Graders run={latest} kinds={kinds} />
          <TrendChart runs={completed} />
        </>
      ) : (
        <FirstRun />
      )}
    </div>
  );
}
