import { CircleHelp, CircleStop } from "lucide-react";
import { memo } from "react";
import { formatTime } from "../lib/format";
import { isTerminal, type RunPhase, type Turn } from "../lib/run";
import { AgentBadge } from "./AgentBadge";
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
        <div className="space-y-2">
          <p className="flex max-w-[72ch] gap-2 text-[15px] leading-relaxed">
            <CircleHelp aria-hidden className="mt-1 size-4 shrink-0 text-agent-ceo" />
            <span>{run.clarification}</span>
          </p>
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
      return (
        <p className="flex items-center gap-1.5 text-sm text-muted">
          <CircleStop aria-hidden className="size-4" />
          You stopped this request before it finished.
        </p>
      );
    default:
      if (!turn.live) return <p className="text-sm text-muted">No answer was recorded for this request.</p>;
      return (
        <p role="status" className="flex items-center gap-2 text-sm text-muted">
          <Spinner />
          {PHASE_LABEL[run.phase]}
        </p>
      );
  }
}

export const TurnView = memo(function TurnView({ turn }: { turn: Turn }) {
  const showStatusAboveAnswer = !isTerminal(turn.run.phase);
  return (
    <article className="space-y-3">
      <header className="flex items-baseline justify-between gap-3">
        <h2 className="text-lg leading-snug font-semibold text-ink">{turn.question}</h2>
        <time dateTime={turn.createdAt} className="shrink-0 text-xs text-faint">
          {formatTime(turn.createdAt)}
        </time>
      </header>
      <div className="space-y-3 border-l-2 border-agent-ceo/40 pl-4">
        <AgentBadge name="ceo" />
        <RunProgress run={turn.run} live={showStatusAboveAnswer} />
        <AssistantBody turn={turn} />
      </div>
    </article>
  );
});
