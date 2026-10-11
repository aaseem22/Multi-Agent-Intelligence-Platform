import { ArrowRight, Ban, ClipboardCheck, CornerDownRight, Flag, ListChecks, MessageCircleQuestion, OctagonAlert, Play, RotateCcw, Wrench, type LucideIcon } from "lucide-react";
import { memo, useState } from "react";
import { AgentName } from "../components/AgentName";
import { JudgeDetail } from "../components/JudgeDetail";
import { RichText } from "../components/RichText";
import { agentStroke } from "../lib/agents";
import { formatArgs, parseServerTime } from "../lib/format";
import type { StreamEvent, StreamEventType } from "../types/events";
import { fmtScore } from "./lib";
import { Mark } from "./ui";

const ICON: Record<StreamEventType, LucideIcon> = {
  plan: ListChecks,
  agent_started: Play,
  tool_call: Wrench,
  peer_message: ArrowRight,
  agent_result: Flag,
  eval_result: ClipboardCheck,
  recovery: RotateCcw,
  final: Flag,
  clarification: MessageCircleQuestion,
  error: OctagonAlert,
};

const RECOVERY_WORD = { retry: "Retried with reviewer feedback", replan: "Asked the CEO to replan", clarify: "Asked for clarification", give_up: "Gave up" } as const;

function isStreamEvent(value: Record<string, unknown>): boolean {
  return typeof value.type === "string" && value.type in ICON;
}

function agentOf(event: StreamEvent): string | null {
  switch (event.type) {
    case "agent_started":
    case "tool_call":
    case "eval_result":
    case "recovery":
      return event.agent;
    case "agent_result":
      return event.result.agent;
    case "peer_message":
      return event.message.sender;
    case "error":
      return event.agent;
    default:
      return "ceo";
  }
}

function Body({ event }: { event: StreamEvent }) {
  switch (event.type) {
    case "plan":
      return (
        <div className="space-y-1.5">
          <p className="text-sm text-ink">
            <AgentName name="ceo" /> planned {event.subtasks.length} {event.subtasks.length === 1 ? "subtask" : "subtasks"}
          </p>
          {event.rationale ? <p className="text-sm text-muted">{event.rationale}</p> : null}
          <ul className="space-y-0.5 text-sm">
            {event.subtasks.map((s) => (
              <li key={s.id} className="flex gap-2">
                <span className="font-mono text-2xs leading-5 text-faint">{s.id}</span>
                <AgentName name={s.assigned_to} />
              </li>
            ))}
          </ul>
        </div>
      );
    case "agent_started":
      return (
        <div>
          <p className="text-sm text-ink">
            <AgentName name={event.agent} /> started {event.mode === "peer" ? "answering a peer request" : <span className="font-mono text-2xs text-muted">{event.subtask_id}</span>}
          </p>
          <p className="mt-0.5 line-clamp-3 text-sm text-ink-2">{event.instruction}</p>
        </div>
      );
    case "tool_call":
      return (
        <p className="min-w-0 font-mono text-xs break-all text-ink-2">
          <AgentName name={event.agent} className="font-sans text-sm" /> <span className="font-medium text-ink">{event.tool}</span>({formatArgs(event.args)})
        </p>
      );
    case "peer_message": {
      const { message } = event;
      return (
        <div>
          <p className="flex flex-wrap items-center gap-x-1.5 text-sm text-ink">
            <AgentName name={message.sender} />
            <ArrowRight aria-label="to" size={13} strokeWidth={1.75} className="text-faint" />
            <AgentName name={message.recipient} />
            <span className="font-mono text-2xs text-muted">
              {message.type.replace("_", " ")}, hop {message.hop_count}
            </span>
          </p>
          <p className="mt-0.5 text-sm text-ink-2">{message.content}</p>
          {event.refused ? (
            <p className="mt-1 flex items-start gap-1.5 text-sm text-danger">
              <Ban aria-hidden size={14} strokeWidth={1.75} className="mt-0.5 shrink-0" />
              Refused: {event.refusal_reason ?? "guard tripped"}
              <span className="font-mono text-2xs text-muted">chain {message.chain.join(" > ")}</span>
            </p>
          ) : null}
        </div>
      );
    }
    case "agent_result": {
      const { result } = event;
      return (
        <div className="space-y-1.5">
          <p className="text-sm text-ink">
            <AgentName name={result.agent} /> returned <span className="font-medium">{result.status}</span>
            {event.mode === "peer" ? " to its peer" : ""}
          </p>
          <p className="text-sm text-ink-2">
            <RichText text={result.answer} />
          </p>
          {result.error ? <p className="text-sm text-danger">{result.error}</p> : null}
          {result.evidence.length > 0 ? (
            <ul className="space-y-0.5 border-l border-line pl-2.5">
              {result.evidence.map((e) => (
                <li key={e.source_ref} className="text-xs text-muted">
                  <code className="font-mono text-2xs text-ink-2">{e.source_ref}</code> {e.summary}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-warn">No evidence cited.</p>
          )}
        </div>
      );
    }
    case "eval_result": {
      const { result } = event;
      return (
        <div className="space-y-1.5">
          <p className="flex flex-wrap items-center gap-x-2 text-sm text-ink">
            <Mark state={result.passed ? "pass" : "fail"} size="sm" />
            <span>
              <span className="font-medium">{result.stage}</span> review of <AgentName name={event.agent} />
            </span>
            <span className="font-mono text-2xs text-muted">
              attempt {event.attempt}
              {result.score !== null ? `, score ${fmtScore(result.score)}` : ""}
            </span>
          </p>
          {result.reasons.length > 0 ? (
            <ul className="list-disc pl-5 text-sm text-ink-2">
              {result.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          ) : null}
          {event.judge ? (
            <details className="group/j">
              <summary className="cursor-pointer text-xs text-muted hover:text-ink">Judge detail, {event.judge.dimensions.length} dimensions</summary>
              <div className="mt-2">
                <JudgeDetail judge={event.judge} compact />
              </div>
            </details>
          ) : null}
        </div>
      );
    }
    case "recovery":
      return (
        <div className="space-y-1">
          <p className="text-sm font-medium text-ink">
            {RECOVERY_WORD[event.action]}: <AgentName name={event.agent} />, after attempt {event.attempt}
          </p>
          {event.reasons.length > 0 ? <p className="text-sm text-muted">{event.reasons.join("; ")}</p> : null}
          {event.feedback ? <p className="border-l-2 border-accent/50 pl-2.5 text-sm text-ink-2">{event.feedback}</p> : null}
        </div>
      );
    case "final":
      return (
        <div className="space-y-1">
          <p className="text-sm font-medium text-ink">Final answer, {event.answer.claims.length} claims</p>
          <p className="text-sm text-ink-2">
            <RichText text={event.answer.answer} />
          </p>
          {event.answer.unanswered.length > 0 ? <p className="text-xs text-warn">Not answered: {event.answer.unanswered.join(" ")}</p> : null}
        </div>
      );
    case "clarification":
      return (
        <p className="text-sm text-ink">
          <AgentName name="ceo" /> asked back: {event.question}
        </p>
      );
    case "error":
      return <p className="text-sm text-danger">{event.message}</p>;
  }
}

const TOOLISH: StreamEventType[] = ["tool_call"];

/** Every stream event of the trial as a timeline, with time since the first event. */
export const Transcript = memo(function Transcript({ events: raw }: { events: Record<string, unknown>[] }) {
  const [showTools, setShowTools] = useState(true);
  const events = raw.filter(isStreamEvent) as unknown as StreamEvent[];
  if (events.length === 0) return <p className="text-sm text-muted">No transcript was stored for this trial.</p>;
  const start = parseServerTime(events[0].timestamp).getTime();
  const shown = showTools ? events : events.filter((e) => !TOOLISH.includes(e.type));
  const tools = events.length - events.filter((e) => !TOOLISH.includes(e.type)).length;

  return (
    <div className="space-y-3">
      <label className="flex w-fit cursor-pointer items-center gap-2 text-sm text-ink-2">
        <input type="checkbox" checked={showTools} onChange={(e) => setShowTools(e.target.checked)} className="size-4 accent-[var(--color-ink)]" />
        Show {tools} tool {tools === 1 ? "call" : "calls"}
      </label>
      <ol className="relative">
        {shown.map((event, i) => {
          const Icon = ICON[event.type];
          const agent = agentOf(event);
          const offset = (parseServerTime(event.timestamp).getTime() - start) / 1000;
          const peer = event.type === "agent_started" && event.mode === "peer";
          const alert = (event.type === "peer_message" && event.refused) || event.type === "error" || (event.type === "eval_result" && !event.result.passed);
          return (
            <li key={i} className="grid grid-cols-[3.25rem_1.75rem_minmax(0,1fr)] gap-x-2 pb-3">
              <span className="pt-0.5 text-right font-mono text-2xs text-faint tabular-nums">+{offset.toFixed(1)}s</span>
              <span className="relative flex justify-center">
                {i < shown.length - 1 ? <span aria-hidden className="absolute top-6 -bottom-3 w-px bg-line" /> : null}
                <span
                  className={`relative inline-flex size-6 items-center justify-center rounded-full border bg-surface ${alert ? "border-danger/40 text-danger" : event.type === "recovery" ? "border-accent/50 text-accent" : "border-line text-muted"}`}
                >
                  {peer ? <CornerDownRight aria-hidden size={12} strokeWidth={2} /> : <Icon aria-hidden size={12} strokeWidth={2} />}
                  {agent ? <span aria-hidden className={`absolute -right-0.5 -bottom-0.5 size-2 rounded-full ring-2 ring-surface ${agentStroke(agent)}`} /> : null}
                </span>
              </span>
              <div className="min-w-0 pt-0.5">
                <Body event={event} />
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
});
