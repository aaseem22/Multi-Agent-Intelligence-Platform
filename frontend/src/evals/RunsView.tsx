import { ArrowRight, ListChecks, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { evalsClient } from "../api/evals";
import { ApiError } from "../api/http";
import { EmptyState, ErrorState, LoadingState, Spinner } from "../components/States";
import { evalsHref } from "../hooks/useHashRoute";
import { errorMessage, formatRelative } from "../lib/format";
import type { RunConfig, RunProgress, RunSummary } from "../types/evals";
import { RunLauncher } from "./RunLauncher";
import { configSummary, isActive, pct, fmtScore, useEvals } from "./lib";
import { Meter, RunStatusText, SectionHead } from "./ui";

const POLL_MS = 2500;

/** Polls /progress while the run is active; calls onSettled once when it stops. */
function useRunProgress(runId: string, onSettled: () => void): RunProgress | null {
  const [progress, setProgress] = useState<RunProgress | null>(null);
  const settledRef = useRef(onSettled);
  useEffect(() => {
    settledRef.current = onSettled;
  });

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const tick = async () => {
      try {
        const client = await evalsClient();
        const next = await client.getProgress(runId, controller.signal);
        setProgress(next);
        if (isActive(next.status)) timer = window.setTimeout(tick, POLL_MS);
        else settledRef.current();
      } catch {
        if (!controller.signal.aborted) timer = window.setTimeout(tick, POLL_MS * 2);
      }
    };
    void tick();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [runId]);

  return progress;
}

function LiveRun({ run, onSettled }: { run: RunSummary; onSettled: () => void }) {
  const progress = useRunProgress(run.run_id, onSettled);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const done = progress?.trials_done ?? run.trials_done;
  const total = progress?.trials_total ?? run.trials_total;
  const status = progress?.status ?? run.status;
  const remaining = Math.max(0, total - done);

  const cancel = async () => {
    setCancelling(true);
    setCancelError(null);
    try {
      await (await evalsClient()).cancelRun(run.run_id);
    } catch (error) {
      setCancelError(errorMessage(error));
      setCancelling(false);
    }
  };

  return (
    <section aria-labelledby="live-run" className="card overflow-hidden">
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="live-run" className="flex items-center gap-2 text-base font-semibold text-ink">
              <span aria-hidden className="live-dot" />
              Run in progress
            </h2>
            <p className="mt-0.5 text-sm text-muted">
              <a href={evalsHref({ kind: "run", runId: run.run_id })} className="link font-mono text-xs">
                {run.run_id}
              </a>{" "}
              {configSummary(run)}
            </p>
          </div>
          <button type="button" onClick={cancel} disabled={cancelling || !isActive(status)} className="btn btn-secondary">
            <Square aria-hidden size={13} strokeWidth={2} />
            {cancelling ? "Cancelling" : "Cancel run"}
          </button>
        </div>
        <div className="space-y-2">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-ink">
              <span className="font-semibold tabular-nums">{done}</span> of <span className="tabular-nums">{total}</span> trials graded
            </span>
            <span className="text-xs text-muted">{remaining > 0 ? `${remaining} to go` : "Finishing"}</span>
          </div>
          <Meter value={total ? done / total : 0} tone="bg-accent" label="Trials graded" />
        </div>
        <p role="status" aria-live="polite" className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-block bg-subtle px-3 py-2 text-sm text-ink-2">
          {progress?.current_task ? <code className="font-mono text-xs text-ink">{progress.current_task}</code> : null}
          <span>{progress?.message || "Waiting for the runner to report."}</span>
          {isActive(status) ? <Spinner className="text-muted" /> : null}
        </p>
        {cancelError ? <p className="text-sm text-danger">Could not cancel: {cancelError}</p> : null}
      </div>
    </section>
  );
}

function RunRow({ run }: { run: RunSummary }) {
  const k = run.config.trials;
  return (
    <li className="border-t border-line first:border-t-0">
      <a
        href={evalsHref({ kind: "run", runId: run.run_id })}
        className="group grid gap-x-6 gap-y-2 px-5 py-4 transition-colors hover:bg-subtle/60 md:grid-cols-[minmax(0,1fr)_repeat(3,5.5rem)_1rem] md:items-center"
      >
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-mono text-sm font-medium text-ink">{run.run_id}</span>
            <RunStatusText status={run.status} />
            <span className="text-xs text-faint">{formatRelative(run.created_at)}</span>
          </p>
          <p className="mt-0.5 truncate text-xs text-muted" title={configSummary(run)}>
            {configSummary(run)}
          </p>
          {run.error && run.status !== "completed" ? <p className="mt-0.5 text-xs text-muted">{run.error}</p> : null}
        </div>
        <dl className="contents text-sm">
          {[
            ["Pass rate", pct(run.pass_rate)],
            [k > 1 ? `pass@${k} / ^${k}` : "pass@1", k > 1 ? `${pct(run.pass_at_k)} / ${pct(run.pass_hat_k)}` : pct(run.pass_at_k)],
            ["Mean score", fmtScore(run.mean_score)],
          ].map(([term, value]) => (
            <div key={term} className="flex items-baseline justify-between gap-2 md:block md:text-right">
              <dt className="text-xs text-muted md:text-2xs">{term}</dt>
              <dd className="font-medium text-ink tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        <ArrowRight aria-hidden size={15} strokeWidth={1.75} className="hidden text-faint transition-transform group-hover:translate-x-0.5 md:block" />
      </a>
    </li>
  );
}

export function RunsView() {
  const [runs, reload] = useEvals((client, signal) => client.getRuns(signal), "evals-runs");
  const [datasets] = useEvals((client, signal) => client.getDatasets(signal), "evals-datasets");
  const list = runs.data ?? [];
  const active = list.find((run) => isActive(run.status));

  const start = async (config: RunConfig): Promise<string | null> => {
    try {
      await (await evalsClient()).startRun(config);
      reload();
      return null;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) return "A run is already in progress. Wait for it to finish or cancel it first.";
      if (error instanceof ApiError && error.status === 422) return `The backend rejected this configuration: ${error.message}`;
      return errorMessage(error);
    }
  };

  return (
    <div className="space-y-5">
      {active ? <LiveRun key={active.run_id} run={active} onSettled={reload} /> : null}

      <RunLauncher datasets={datasets} busy={Boolean(active)} onStart={start} />

      <section aria-labelledby="run-list" className="card overflow-hidden">
        <div className="border-b border-line px-5 py-4">
          <SectionHead id="run-list" title="All runs">
            Newest first. Open a run to see every trial and its transcript.
          </SectionHead>
        </div>
        {runs.status === "loading" && !runs.data ? (
          <div className="p-5">
            <LoadingState label="Loading runs" />
          </div>
        ) : runs.status === "error" && !runs.data ? (
          <div className="p-5">
            <ErrorState title="Could not load runs" detail={runs.error} onRetry={reload} />
          </div>
        ) : list.length === 0 ? (
          <EmptyState title="No runs yet" icon={<ListChecks size={20} strokeWidth={1.75} />}>
            Configure a run above. Each one seeds a fresh fixture database, so results compare across runs.
          </EmptyState>
        ) : (
          <ul>
            {list.map((run) => (
              <RunRow key={run.run_id} run={run} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
