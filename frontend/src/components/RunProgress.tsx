import { memo } from "react";
import { formatArgs } from "../lib/format";
import type { AgentRun, RunState } from "../lib/run";
import { AgentName } from "./AgentName";
import { RunStateLabel } from "./RunStatus";

const NO_DEPS: string[] = [];

/** Eval results written out as a sentence; failures switch to red ink. */
function EvalLine({ run }: { run: AgentRun }) {
  if (run.evals.length === 0) return null;
  return (
    <p className="text-2xs text-pencil" aria-label="Evaluation results">
      Checks:{" "}
      {run.evals.map((result, index) => (
        <span key={`${result.stage}-${index}`} title={result.reasons.join(" ") || undefined}>
          {index > 0 ? ", " : ""}
          <span className={result.passed ? "text-graphite" : "font-semibold text-refuse"}>
            {result.stage} {result.passed ? "passed" : "failed"}
            {result.score !== null ? ` (${result.score.toFixed(2)})` : ""}
          </span>
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
      <summary className="cursor-pointer text-2xs text-pencil hover:text-ink">
        <span aria-hidden className="mr-1 inline-block font-mono transition-transform group-open/log:rotate-90">
          ›
        </span>
        {run.tools.length} tool {run.tools.length === 1 ? "call" : "calls"}
        {run.result ? `, ${evidenceCount} ${evidenceCount === 1 ? "piece" : "pieces"} of evidence` : ""}
      </summary>
      <ol className="mt-1.5 space-y-0.5 border-l border-rule pl-3">
        {run.tools.map((call, index) => (
          <li key={`${call.tool}-${index}`} className="flex min-w-0 font-mono text-2xs animate-enter">
            <span className="shrink-0 text-ink">{call.tool}</span>
            <span className="min-w-0 truncate text-pencil" title={formatArgs(call.args)}>
              ({formatArgs(call.args)})
            </span>
          </li>
        ))}
        {run.result ? <li className="pt-1 text-xs text-graphite italic">{run.result.answer}</li> : null}
        {run.result?.error ? <li className="text-xs text-refuse">{run.result.error}</li> : null}
      </ol>
    </details>
  );
}

interface RunRowProps {
  run: AgentRun;
  live: boolean;
  marker: string;
  dependsOn?: string[];
}

function RunRow({ run, live, marker, dependsOn = NO_DEPS }: RunRowProps) {
  return (
    <li className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-2 border-t border-rule py-2.5 first:border-t-0 sm:grid-cols-[1.75rem_5.5rem_minmax(0,1fr)_auto]">
      <span className="pt-px font-mono text-2xs text-pencil">{marker}</span>
      <div className="flex items-baseline justify-between gap-3 sm:contents">
        <AgentName name={run.agent} className="text-sm" />
        <span className="sm:order-last sm:pt-px">
          <RunStateLabel state={run.state} />
        </span>
      </div>
      <div className="col-start-2 min-w-0 space-y-1.5 sm:col-start-3 sm:row-start-1">
        {dependsOn.length > 0 ? <p className="text-2xs text-pencil">Waits for {dependsOn.join(", ")}</p> : null}
        {run.instruction ? (
          <p className="text-sm text-ink">{run.instruction}</p>
        ) : run.mode === "peer" ? (
          <p className="text-sm text-graphite italic">Answering a peer request</p>
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

/** The CEO's plan as a numbered table, with each agent's working notes beneath its row. */
export const RunProgress = memo(function RunProgress({ run, live }: RunProgressProps) {
  if (!run.plan && run.runs.length === 0) return null;

  const taskRuns = run.runs.filter((item) => item.mode === "task");
  const peerRuns = run.runs.filter((item) => item.mode === "peer");
  const toolCount = run.runs.reduce((sum, item) => sum + item.tools.length, 0);
  const subtaskCount = run.plan?.subtasks.length ?? taskRuns.length;
  const dependsOn = new Map((run.plan?.subtasks ?? []).map((s) => [s.id, s.depends_on]));

  return (
    <details open={live} className="group/plan border-y border-rule-strong">
      <summary className="flex cursor-pointer flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2 hover:text-ink">
        <span className="text-sm font-semibold">
          <span aria-hidden className="mr-1.5 inline-block font-mono text-pencil transition-transform group-open/plan:rotate-90">
            ›
          </span>
          The CEO's plan
        </span>
        <span className="text-xs text-graphite">
          {subtaskCount} {subtaskCount === 1 ? "subtask" : "subtasks"}, {toolCount} tool{" "}
          {toolCount === 1 ? "call" : "calls"}
          {peerRuns.length > 0 ? `, ${peerRuns.length} peer ${peerRuns.length === 1 ? "answer" : "answers"}` : ""}
        </span>
      </summary>
      <div className="border-t border-rule pb-1">
        {run.plan?.rationale ? (
          <p className="max-w-[68ch] pt-2.5 pb-1 text-sm text-graphite italic">{run.plan.rationale}</p>
        ) : null}
        <ol>
          {taskRuns.map((item, index) => (
            <RunRow
              key={item.key}
              run={item}
              live={live}
              marker={`${index + 1}.`}
              dependsOn={dependsOn.get(item.subtaskId) ?? []}
            />
          ))}
        </ol>
        {peerRuns.length > 0 ? (
          <>
            <p className="mt-1 border-t border-rule pt-2.5 text-xs text-graphite italic">
              Answered for other departments
            </p>
            <ul>
              {peerRuns.map((item) => (
                <RunRow key={item.key} run={item} live={live} marker="↳" />
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </details>
  );
});
