import { ChevronRight, GitFork, ShieldCheck, ShieldX, Wrench } from "lucide-react";
import { memo } from "react";
import { formatArgs } from "../lib/format";
import type { AgentRun, RunState } from "../lib/run";
import { AgentBadge } from "./AgentBadge";
import { RunStateLabel } from "./RunStatus";

const NO_DEPS: string[] = [];

function EvalChips({ run }: { run: AgentRun }) {
  if (run.evals.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1" aria-label="Evaluation results">
      {run.evals.map((result, index) => (
        <li
          key={`${result.stage}-${index}`}
          title={result.reasons.join(" ") || undefined}
          className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${
            result.passed ? "bg-ok/10 text-ok" : "bg-fail/10 text-fail"
          }`}
        >
          {result.passed ? <ShieldCheck aria-hidden className="size-3" /> : <ShieldX aria-hidden className="size-3" />}
          {result.stage} {result.passed ? "passed" : "failed"}
          {result.score !== null ? ` (${result.score.toFixed(2)})` : ""}
        </li>
      ))}
    </ul>
  );
}

interface RunRowProps {
  run: AgentRun;
  live: boolean;
  dependsOn?: string[];
}

function RunRow({ run, live, dependsOn = NO_DEPS }: RunRowProps) {
  const hasDetail = run.tools.length > 0 || run.result !== null;
  return (
    <li className="py-2.5">
      {dependsOn.length > 0 ? <p className="mb-1 text-xs text-faint">Waits for {dependsOn.join(", ")}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <AgentBadge name={run.agent} />
        {run.mode === "peer" ? (
          <span className="inline-flex items-center gap-1 text-xs text-muted">
            <GitFork aria-hidden className="size-3" />
            answering a peer
          </span>
        ) : null}
        <span className="ml-auto">
          <RunStateLabel state={run.state} />
        </span>
      </div>
      {run.instruction ? <p className="mt-1 text-sm text-ink/85">{run.instruction}</p> : null}
      {hasDetail ? (
        <details className="group mt-1.5" open={live}>
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-muted hover:text-ink">
            <ChevronRight aria-hidden className="size-3 transition-transform group-open:rotate-90" />
            {run.tools.length} tool {run.tools.length === 1 ? "call" : "calls"}
            {run.result ? `, ${run.result.evidence.length} evidence` : ""}
          </summary>
          <ol className="mt-1.5 space-y-1 border-l border-line pl-3">
            {run.tools.map((call, index) => (
              <li key={`${call.tool}-${index}`} className="flex gap-1.5 text-xs">
                <Wrench aria-hidden className="mt-0.5 size-3 shrink-0 text-faint" />
                <code className="font-mono text-ink">{call.tool}</code>
                <span className="min-w-0 truncate font-mono text-muted" title={formatArgs(call.args)}>
                  ({formatArgs(call.args)})
                </span>
              </li>
            ))}
            {run.result ? <li className="pt-1 text-xs text-muted">{run.result.answer}</li> : null}
            {run.result?.error ? <li className="text-xs text-fail">{run.result.error}</li> : null}
          </ol>
        </details>
      ) : null}
      <div className="mt-1.5">
        <EvalChips run={run} />
      </div>
    </li>
  );
}

interface RunProgressProps {
  run: RunState;
  live: boolean;
}

/** CEO plan plus per-agent status. Open while the request runs, collapsible afterwards. */
export const RunProgress = memo(function RunProgress({ run, live }: RunProgressProps) {
  if (!run.plan && run.runs.length === 0) return null;

  const taskRuns = run.runs.filter((item) => item.mode === "task");
  const peerRuns = run.runs.filter((item) => item.mode === "peer");
  const toolCount = run.runs.reduce((sum, item) => sum + item.tools.length, 0);
  const subtaskCount = run.plan?.subtasks.length ?? taskRuns.length;
  const dependsOn = new Map((run.plan?.subtasks ?? []).map((s) => [s.id, s.depends_on]));

  return (
    <details open={live} className="group/plan rounded-lg border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm">
        <ChevronRight aria-hidden className="size-4 text-faint transition-transform group-open/plan:rotate-90" />
        <span className="font-medium">CEO plan</span>
        <span className="text-muted">
          {subtaskCount} {subtaskCount === 1 ? "subtask" : "subtasks"}, {toolCount} tool{" "}
          {toolCount === 1 ? "call" : "calls"}
          {peerRuns.length > 0 ? `, ${peerRuns.length} peer ${peerRuns.length === 1 ? "answer" : "answers"}` : ""}
        </span>
      </summary>
      <div className="border-t border-line px-3 pb-2">
        {run.plan?.rationale ? <p className="pt-2.5 text-sm text-muted italic">{run.plan.rationale}</p> : null}
        <ul className="divide-y divide-line">
          {taskRuns.map((item) => (
            <RunRow key={item.key} run={item} live={live} dependsOn={dependsOn.get(item.subtaskId) ?? []} />
          ))}
        </ul>
        {peerRuns.length > 0 ? (
          <>
            <p className="mt-2 text-xs font-medium text-muted">Peer answers</p>
            <ul className="divide-y divide-line">
              {peerRuns.map((item) => (
                <RunRow key={item.key} run={item} live={live} />
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </details>
  );
});
