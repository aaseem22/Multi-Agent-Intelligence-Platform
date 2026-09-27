import { memo } from "react";
import { formatTime } from "../lib/format";
import { isTerminal, type RunPhase, type Turn } from "../lib/run";
import { AgentName } from "./AgentName";
import { FinalAnswerView, TraceLink } from "./FinalAnswerView";
import { RunProgress } from "./RunProgress";
import { ErrorState, Spinner } from "./States";

const PHASE_LABEL: Partial<Record<RunPhase, string>> = {
  planning: "Planning which departments to ask",
  running: "Departments are working",
  synthesising: "Combining the department answers",
};

function AssistantBody({ turn }: { turn: Turn }) {
  const { run } = turn;
  switch (run.phase) {
    case "done":
      return run.final ? <FinalAnswerView outcome={run.final} traceUrl={run.traceUrl} /> : null;
    case "clarification":
      return (
        <div className="space-y-3">
          <p className="max-w-[66ch] text-read">{run.clarification}</p>
          <TraceLink url={run.traceUrl} />
        </div>
      );
    case "error":
      return (
        <ErrorState
          title={run.error?.agent ? `The ${run.error.agent} agent failed` : "The request failed"}
          detail={run.error?.message ?? "No error detail was provided."}
        />
      );
    case "cancelled":
      return <p className="text-sm text-graphite italic">You stopped this request before it finished.</p>;
    default:
      if (!turn.live) return <p className="text-sm text-graphite italic">No answer was recorded for this request.</p>;
      return (
        <p role="status" className="flex items-baseline gap-2.5 text-sm text-graphite italic">
          {PHASE_LABEL[run.phase]}
          <Spinner className="text-ink" />
        </p>
      );
  }
}

const BYLINE: Partial<Record<RunPhase, string>> = {
  clarification: "asks a question back",
  done: "answers",
  error: "reports a failure",
  cancelled: "did not finish",
};

export const TurnView = memo(function TurnView({ turn }: { turn: Turn }) {
  const showStatusAboveAnswer = !isTerminal(turn.run.phase);
  const byline = BYLINE[turn.run.phase] ?? "is working on it";
  return (
    <article className="space-y-5">
      <header>
        <time dateTime={turn.createdAt} className="font-mono text-2xs text-pencil">
          {formatTime(turn.createdAt)}
        </time>
        <h2 className="mt-1 max-w-[30ch] text-xl font-medium text-balance text-ink sm:text-2xl">{turn.question}</h2>
      </header>
      <RunProgress run={turn.run} live={showStatusAboveAnswer} />
      <div className="space-y-2">
        <p className="text-xs text-graphite">
          <AgentName name="ceo" /> {byline}
        </p>
        <AssistantBody turn={turn} />
      </div>
    </article>
  );
});
