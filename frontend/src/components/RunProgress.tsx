import { ChevronRight, CornerDownRight, ListChecks } from "lucide-react";
import { memo } from "react";
import { formatArgs } from "../lib/format";
import type { AgentRun, RunState } from "../lib/run";
import { AgentAvatar, AgentName } from "./AgentName";
import { RichText } from "./RichText";
import { RunStateLabel } from "./RunStatus";

const NO_DEPS: string[] = [];

/** Eval results as small chips; a failed check turns red. */
function EvalLine({ run }: { run: AgentRun }) {
  if (run.evals.length === 0) return null;
  return (
    <p className="flex flex-wrap items-center gap-1.5" aria-label="Evaluation results">
      <span className="text-2xs text-faint">Checks</span>
      {run.evals.map((result, index) => (
        <span
          key={`${result.stage}-${index}`}
          title={result.reasons.join(" ") || undefined}
          className={`chip ${result.passed ? "bg-subtle text-ink-2" : "bg-danger-soft text-danger"}`}
        >
          {result.stage} {result.passed ? "passed" : "failed"}
          {result.score !== null ? ` ${result.score.toFixed(2)}` : ""}
        </span>
      ))}
    </p>
  );
}

function WorkLog({ run, live }: { run: AgentRun; live: boolean }) {
  const hasDetail = run.tools.length > 0 || run.result !== null;
  if (!hasDetail) return null;
  const evidenceCount = run.result?.evidence.length ?? 0;
  return (
    <details className="group/log" open={live}>
      <summary className="inline-flex cursor-pointer items-center gap-1 rounded-md text-xs text-muted transition-colors hover:text-ink">
        <ChevronRight aria-hidden size={13} strokeWidth={2} className="transition-transform duration-200 group-open/log:rotate-90" />
        {run.tools.length} tool {run.tools.length === 1 ? "call" : "calls"}
        {run.result ? `, ${evidenceCount} ${evidenceCount === 1 ? "piece" : "pieces"} of evidence` : ""}
      </summary>
      <div className="mt-2 space-y-2 rounded-block bg-subtle p-3">
        {run.tools.length > 0 ? (
          <ol className="space-y-1">
            {run.tools.map((call, index) => (
              <li key={`${call.tool}-${index}`} className="flex min-w-0 items-baseline gap-1 font-mono text-2xs animate-enter">
                <span className="shrink-0 font-medium text-ink">{call.tool}</span>
                <span className="min-w-0 truncate text-muted" title={formatArgs(call.args)}>
                  ({formatArgs(call.args)})
                </span>
              </li>
            ))}
          </ol>
        ) : null}
        {run.result ? <p className="text-sm leading-relaxed text-ink-2">
            <RichText text={run.result.answer} />
          </p> : null}
        {run.result?.error ? <p className="text-sm text-danger">{run.result.error}</p> : null}
      </div>
    </details>
  );
}

interface RunRowProps {
  run: AgentRun;
  live: boolean;
  peer?: boolean;
  dependsOn?: string[];
}

function RunRow({ run, live, peer = false, dependsOn = NO_DEPS }: RunRowProps) {
  return (
    <li className="flex gap-3 border-t border-line px-4 py-3.5 first:border-t-0">
      {peer ? (
        <CornerDownRight aria-hidden size={16} strokeWidth={1.75} className="mt-2 shrink-0 text-faint" />
      ) : null}
      <AgentAvatar name={run.agent} />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 pt-1">
          <AgentName name={run.agent} className="text-base" />
          <RunStateLabel state={run.state} />
        </div>
        {dependsOn.length > 0 ? <p className="text-2xs text-faint">Waits for {dependsOn.join(", ")}</p> : null}
        {run.instruction ? (
          <p className="text-sm leading-relaxed text-ink-2">{run.instruction}</p>
        ) : peer ? (
          <p className="text-sm text-muted">Answering a peer request</p>
        ) : null}
        <WorkLog run={run} live={live} />
        <EvalLine run={run} />
      </div>
    </li>
  );
}

interface RunProgressProps {
  run: RunState;
  live: boolean;
}

/** The CEO's plan as a card: one row per department, with each agent's working notes beneath. */
export const RunProgress = memo(function RunProgress({ run, live }: RunProgressProps) {
  if (!run.plan && run.runs.length === 0) return null;

  const taskRuns = run.runs.filter((item) => item.mode === "task");
  const peerRuns = run.runs.filter((item) => item.mode === "peer");
  const toolCount = run.runs.reduce((sum, item) => sum + item.tools.length, 0);
  const subtaskCount = run.plan?.subtasks.length ?? taskRuns.length;
  const dependsOn = new Map((run.plan?.subtasks ?? []).map((s) => [s.id, s.depends_on]));

  return (
    <details open={live} className="group/plan card overflow-hidden animate-enter">
      <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 transition-colors hover:bg-subtle/60">
        <span className="flex items-center gap-2 text-base font-medium text-ink">
          <ListChecks aria-hidden size={16} strokeWidth={1.75} className="text-muted" />
          Execution plan
        </span>
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="mono-tag">
            {subtaskCount} {subtaskCount === 1 ? "subtask" : "subtasks"}
          </span>
          <span className="mono-tag">
            {toolCount} tool {toolCount === 1 ? "call" : "calls"}
          </span>
          {peerRuns.length > 0 ? (
            <span className="mono-tag bg-accent-soft! text-accent-strong!">
              {peerRuns.length} peer {peerRuns.length === 1 ? "answer" : "answers"}
            </span>
          ) : null}
        </span>
        <ChevronRight
          aria-hidden
          size={16}
          strokeWidth={1.75}
          className="ml-auto text-faint transition-transform duration-200 group-open/plan:rotate-90"
        />
      </summary>
      <div className="border-t border-line">
        {run.plan?.rationale ? (
          <p className="border-b border-line bg-subtle/50 px-4 py-3 text-sm leading-relaxed text-muted">{run.plan.rationale}</p>
        ) : null}
        <ol>
          {taskRuns.map((item) => (
            <RunRow key={item.key} run={item} live={live} dependsOn={dependsOn.get(item.subtaskId) ?? []} />
          ))}
        </ol>
        {peerRuns.length > 0 ? (
          <>
            <p className="border-t border-line bg-subtle/50 px-4 py-2 text-xs font-medium text-muted">
              Answered for other departments
            </p>
            <ul>
              {peerRuns.map((item) => (
                <RunRow key={item.key} run={item} live={live} peer />
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </details>
  );
});
