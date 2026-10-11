import { memo } from "react";
import { formatTime } from "../lib/format";
import { isAwaitingServer } from "../hooks/useConversation";
import { isTerminal, type RunPhase, type Turn } from "../lib/run";
import { AgentAvatar } from "./AgentName";
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
        <div className="card space-y-4 p-5 animate-enter">
          <p className="max-w-[66ch] text-read text-ink">{run.clarification}</p>
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
      return <p className="text-sm text-muted">You stopped this request before it finished.</p>;
    default:
      if (!turn.live) {
        if (!isAwaitingServer(turn)) return <p className="text-sm text-muted">No answer was recorded for this request.</p>;
        return (
          <p role="status" className="inline-flex items-center gap-2.5 rounded-full bg-accent-soft px-3 py-1.5 text-sm text-accent-strong">
            <span aria-hidden className="live-dot" />
            Still working on this answer. It appears here when it is ready.
            <Spinner />
          </p>
        );
      }
      return (
        <p role="status" className="inline-flex items-center gap-2.5 rounded-full bg-accent-soft px-3 py-1.5 text-sm text-accent-strong">
          <span aria-hidden className="live-dot" />
          {PHASE_LABEL[run.phase]}
          <Spinner />
        </p>
      );
  }
}

const BYLINE: Partial<Record<RunPhase, string>> = {
  clarification: "needs a little more detail",
  done: "answered",
  error: "reported a failure",
  cancelled: "did not finish",
};

export const TurnView = memo(function TurnView({ turn }: { turn: Turn }) {
  const showStatusAboveAnswer = !isTerminal(turn.run.phase);
  const byline = BYLINE[turn.run.phase] ?? "is working on it";
  return (
    <article className="space-y-5 animate-enter">
      <header className="flex flex-col items-end gap-1.5">
        <h2 className="max-w-[85%] rounded-[18px] rounded-br-md bg-bubble px-4 py-2.5 text-read font-normal text-on-bubble shadow-card">
          {turn.question}
        </h2>
        <time dateTime={turn.createdAt} className="pr-1 text-2xs text-faint">
          {formatTime(turn.createdAt)}
        </time>
      </header>

      <div className="flex gap-3">
        <AgentAvatar name="ceo" />
        <div className="min-w-0 flex-1 space-y-4">
          <p className="pt-1.5 text-sm text-muted">
            <span className="font-medium text-ink">CEO</span> {byline}
          </p>
          <RunProgress run={turn.run} live={showStatusAboveAnswer} />
          <AssistantBody turn={turn} />
        </div>
      </div>
    </article>
  );
});
