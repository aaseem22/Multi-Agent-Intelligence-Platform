import { ChevronRight, RotateCw } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { ErrorState, LoadingState } from "../components/States";
import { evalsHref } from "../hooks/useHashRoute";
import { formatRelative } from "../lib/format";
import type { GraderKind, RunSummary, TaskSummary, TrialResult } from "../types/evals";
import { configSummary, graderKinds, humanise, isActive, kindOf, pct, fmtScore, SUITE_COPY, trialState, useEvals, type MarkState } from "./lib";
import { Crumbs, Figure, Mark, RunStatusText } from "./ui";

interface Filters {
  suite: "all" | "capability" | "regression";
  category: string;
  failedOnly: boolean;
}

/** Trial pass rate of one suite and category group (the summary's by_category spans both suites). */
function groupRate(tasks: TaskSummary[]): string {
  const trials = tasks.reduce((sum, t) => sum + t.trials, 0);
  const passes = tasks.reduce((sum, t) => sum + t.passes, 0);
  return `${pct(trials ? passes / trials : null)} of trials passed`;
}

function rateState(rate: number): MarkState {
  return rate >= 1 ? "pass" : rate <= 0 ? "fail" : "unknown";
}

function TrialCell({ trial, runId }: { trial: TrialResult | undefined; runId: string }) {
  if (!trial) return <span className="inline-block size-5 rounded-md border border-dashed border-line-strong" aria-label="Not run yet" />;
  const state = trialState(trial);
  return (
    <a
      href={evalsHref({ kind: "trial", runId, trialId: trial.trial_id })}
      className="group inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 transition-colors hover:bg-subtle"
      aria-label={`Trial ${trial.index + 1}: ${trial.status}, score ${fmtScore(trial.score)}. Open transcript`}
    >
      <Mark state={state} label="" />
      <span className={`font-mono text-2xs tabular-nums ${state === "pass" ? "text-muted" : "text-ink"}`}>{state === "error" ? "err" : fmtScore(trial.score)}</span>
      {trial.recoveries > 0 ? (
        <span className="font-mono text-2xs text-accent" title="Self-evaluation retried an agent in this trial">
          r
        </span>
      ) : null}
    </a>
  );
}

function GraderBreakdown({ task, kinds }: { task: TaskSummary; kinds: Map<string, GraderKind> }) {
  const entries = Object.entries(task.grader_pass_rates);
  return (
    <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
      {entries.map(([name, rate]) => (
        <li key={name} className="flex items-center gap-2 text-sm">
          <Mark state={rateState(rate)} size="sm" label={rate >= 1 ? "Always passed" : rate <= 0 ? "Never passed" : "Passed sometimes"} />
          <span className="min-w-0 flex-1 truncate text-ink-2">{humanise(name)}</span>
          <span className="text-2xs text-faint">{kindOf(name, kinds)}</span>
          <span className="w-10 text-right font-mono text-xs text-ink tabular-nums">{pct(rate)}</span>
        </li>
      ))}
    </ul>
  );
}

function TaskRow({ task, trials, k, runId, kinds }: { task: TaskSummary; trials: (TrialResult | undefined)[]; k: number; runId: string; kinds: Map<string, GraderKind> }) {
  const [open, setOpen] = useState(false);
  const failingGraders = Object.entries(task.grader_pass_rates).filter(([, rate]) => rate < 1).length;
  return (
    <>
      <tr className="border-t border-line align-middle">
        <th scope="row" className="py-2.5 pr-4 pl-5 text-left font-normal">
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="group flex w-full min-w-0 items-start gap-2 text-left">
            <ChevronRight aria-hidden size={14} strokeWidth={1.75} className={`mt-0.5 shrink-0 text-faint transition-transform ${open ? "rotate-90" : ""}`} />
            <span className="min-w-0">
              <span className="font-mono text-xs text-ink">{task.task_id}</span>
              <span className="block max-w-[44ch] truncate text-sm text-ink-2" title={task.question}>
                {task.question}
              </span>
            </span>
          </button>
        </th>
        {Array.from({ length: k }, (_, i) => (
          <td key={i} className="px-1.5 py-2.5">
            <TrialCell trial={trials[i]} runId={runId} />
          </td>
        ))}
        <td className="px-3 py-2.5 text-center">
          <Mark state={task.pass_at_k ? "pass" : "fail"} size="sm" label={task.pass_at_k ? `pass@${k}: yes` : `pass@${k}: no`} />
        </td>
        <td className="px-3 py-2.5 text-center">
          <Mark state={task.pass_hat_k ? "pass" : "fail"} size="sm" label={task.pass_hat_k ? `pass^${k}: yes` : `pass^${k}: no`} />
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-xs text-ink tabular-nums">{fmtScore(task.mean_score)}</td>
        <td className="py-2.5 pr-5 pl-3 text-right text-xs whitespace-nowrap text-muted">
          {failingGraders === 0 ? "All passed" : `${failingGraders} of ${Object.keys(task.grader_pass_rates).length} failed`}
        </td>
      </tr>
      {open ? (
        <tr className="bg-subtle/50">
          <td colSpan={k + 5} className="px-5 py-3 pl-11">
            <p className="mb-2 text-xs text-muted">
              Grader pass rates across {task.trials} {task.trials === 1 ? "trial" : "trials"}
            </p>
            <GraderBreakdown task={task} kinds={kinds} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function Matrix({ run, trials, filters }: { run: RunSummary; trials: TrialResult[]; filters: Filters }) {
  const k = run.config.trials;
  const kinds = useMemo(() => graderKinds(trials), [trials]);
  const byTask = useMemo(() => {
    const map = new Map<string, (TrialResult | undefined)[]>();
    for (const trial of trials) {
      const row = map.get(trial.task_id) ?? [];
      row[trial.index] = trial;
      map.set(trial.task_id, row);
    }
    return map;
  }, [trials]);

  const visible = run.tasks.filter(
    (task) =>
      (filters.suite === "all" || task.suite === filters.suite) &&
      (filters.category === "all" || task.category === filters.category) &&
      (!filters.failedOnly || !task.pass_hat_k),
  );
  const groups = new Map<string, TaskSummary[]>();
  for (const task of visible.toSorted((a, b) => a.suite.localeCompare(b.suite) || a.category.localeCompare(b.category) || a.task_id.localeCompare(b.task_id))) {
    const key = `${task.suite}|${task.category}`;
    groups.set(key, [...(groups.get(key) ?? []), task]);
  }

  if (visible.length === 0) return <p className="px-5 py-8 text-center text-sm text-muted">No task matches these filters.</p>;

  let lastSuite = "";
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] border-collapse text-sm">
        <caption className="sr-only">Task by trial results</caption>
        <thead>
          <tr className="text-2xs text-muted">
            <th scope="col" className="py-2 pr-4 pl-5 text-left font-medium">
              Task
            </th>
            {Array.from({ length: k }, (_, i) => (
              <th key={i} scope="col" className="px-1.5 py-2 text-left font-medium">
                Trial {i + 1}
              </th>
            ))}
            <th scope="col" className="px-3 py-2 font-medium">
              pass@{k}
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              pass^{k}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Mean
            </th>
            <th scope="col" className="py-2 pr-5 pl-3 text-right font-medium">
              Graders
            </th>
          </tr>
        </thead>
        <tbody>
          {[...groups.entries()].map(([key, tasks]) => {
            const [suite, category] = key.split("|") as [keyof typeof SUITE_COPY, string];
            const showSuite = suite !== lastSuite;
            lastSuite = suite;
            return (
              <Fragment key={key}>
                {showSuite ? (
                  <tr className="border-t border-line-strong">
                    <th colSpan={k + 5} scope="rowgroup" className="bg-subtle px-5 py-2 text-left">
                      <span className="text-sm font-semibold text-ink">{SUITE_COPY[suite]?.label ?? suite}</span>
                      <span className="ml-2 text-xs font-normal text-muted">
                        {pct(run.by_suite[suite])} of trials passed. {SUITE_COPY[suite]?.line}
                      </span>
                    </th>
                  </tr>
                ) : null}
                <tr>
                  <th colSpan={k + 5} scope="rowgroup" className="px-5 pt-3 pb-1 text-left text-xs font-medium text-muted">
                    {humanise(category)} <span className="font-normal text-faint">{groupRate(tasks)}</span>
                  </th>
                </tr>
                {tasks.map((task) => (
                  <TaskRow key={task.task_id} task={task} trials={byTask.get(task.task_id) ?? []} k={k} runId={run.run_id} kinds={kinds} />
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FilterBar({ run, filters, onChange }: { run: RunSummary; filters: Filters; onChange: (f: Filters) => void }) {
  const categories = [...new Set(run.tasks.map((t) => t.category))].sort();
  const select = "h-8 rounded-block border border-line bg-surface px-2 text-sm text-ink shadow-card";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-3">
      <label className="flex items-center gap-2 text-sm text-muted">
        Suite
        <select className={select} value={filters.suite} onChange={(e) => onChange({ ...filters, suite: e.target.value as Filters["suite"] })}>
          <option value="all">All</option>
          <option value="regression">Regression</option>
          <option value="capability">Capability</option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm text-muted">
        Category
        <select className={select} value={filters.category} onChange={(e) => onChange({ ...filters, category: e.target.value })}>
          <option value="all">All</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {humanise(c)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex cursor-pointer items-center gap-2 text-sm text-ink">
        <input type="checkbox" checked={filters.failedOnly} onChange={(e) => onChange({ ...filters, failedOnly: e.target.checked })} className="size-4 accent-[var(--color-ink)]" />
        Only tasks with a failed trial
      </label>
      <p className="flex items-center gap-3 text-xs text-muted sm:ml-auto">
        <span className="inline-flex items-center gap-1">
          <Mark state="pass" size="sm" label="" /> pass
        </span>
        <span className="inline-flex items-center gap-1">
          <Mark state="fail" size="sm" label="" /> fail
        </span>
        <span className="inline-flex items-center gap-1">
          <Mark state="error" size="sm" label="" /> error
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="font-mono text-accent">r</span> retried
        </span>
      </p>
    </div>
  );
}

export function RunDetailView({ runId }: { runId: string }) {
  const [run, reloadRun] = useEvals((client, signal) => client.getRun(runId, signal), `evals-run-${runId}`);
  const [trials, reloadTrials] = useEvals((client, signal) => client.getTrials(runId, signal), `evals-run-trials-${runId}`);
  const [filters, setFilters] = useState<Filters>({ suite: "all", category: "all", failedOnly: false });
  const reload = () => {
    reloadRun();
    reloadTrials();
  };

  const crumbs = <Crumbs items={[{ href: evalsHref({ kind: "runs" }), label: "Runs" }, { label: runId }]} />;
  if (run.status === "loading" && !run.data) {
    return (
      <div className="space-y-4">
        {crumbs}
        <div className="card p-6">
          <LoadingState label="Loading run" lines={6} />
        </div>
      </div>
    );
  }
  if (run.status === "error" && !run.data) {
    return (
      <div className="space-y-4">
        {crumbs}
        <ErrorState title="Could not load this run" detail={run.error} onRetry={reload} />
      </div>
    );
  }
  const summary = run.data as RunSummary;
  const k = summary.config.trials;

  return (
    <div className="space-y-5">
      {crumbs}
      <section className="card space-y-5 p-5 sm:p-6" aria-labelledby="run-title">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="run-title" className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono text-lg font-semibold text-ink">{summary.run_id}</span>
              <RunStatusText status={summary.status} />
            </h2>
            <p className="mt-1 text-sm text-muted">
              {configSummary(summary)}. Started {formatRelative(summary.started_at ?? summary.created_at)}.
            </p>
            <p className="mt-0.5 font-mono text-2xs text-muted">
              agents {summary.agent_model}, CEO {summary.ceo_model}, judge {summary.config.judge_enabled ? summary.judge_model : "off"}
            </p>
          </div>
          {isActive(summary.status) ? (
            <button type="button" onClick={reload} className="btn btn-secondary">
              <RotateCw aria-hidden size={14} strokeWidth={1.75} />
              Refresh ({summary.trials_done} of {summary.trials_total})
            </button>
          ) : null}
        </div>
        {summary.error ? <p className="rounded-block bg-subtle px-3 py-2 text-sm text-ink-2">{summary.error}</p> : null}
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 border-t border-line pt-5 sm:grid-cols-4">
          <Figure value={pct(summary.pass_rate)} label="Pass rate" note={`${summary.trials_done} trials graded`} />
          <Figure value={pct(summary.pass_at_k)} label={`pass@${k}`} note="At least one trial passed" />
          <Figure value={pct(summary.pass_hat_k)} label={`pass^${k}`} note="Every trial passed" />
          <Figure value={fmtScore(summary.mean_score)} label="Mean score" note="Weighted, 0 to 1" />
        </div>
      </section>

      <section className="card overflow-hidden" aria-label="Task by trial matrix">
        <FilterBar run={summary} filters={filters} onChange={setFilters} />
        {trials.status === "error" && !trials.data ? (
          <div className="p-5">
            <ErrorState title="Could not load trials" detail={trials.error} onRetry={reloadTrials} />
          </div>
        ) : trials.status === "loading" && !trials.data ? (
          <div className="p-5">
            <LoadingState label="Loading trials" lines={6} />
          </div>
        ) : summary.tasks.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-muted">No task has finished all of its trials yet.</p>
        ) : (
          <Matrix run={summary} trials={trials.data ?? []} filters={filters} />
        )}
      </section>
    </div>
  );
}
