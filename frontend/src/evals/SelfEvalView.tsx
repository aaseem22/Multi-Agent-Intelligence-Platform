import { ArrowUpRight, RotateCcw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { AgentName } from "../components/AgentName";
import { JudgeDetail } from "../components/JudgeDetail";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { chatHref } from "../hooks/useHashRoute";
import { formatRelative } from "../lib/format";
import type { JudgeVerdict, SelfEvalRecord, SelfEvalStats } from "../types/evals";
import { fmtScore, pct, useEvals } from "./lib";
import { Figure, Mark, Meter, SectionHead } from "./ui";

const WINDOWS = [
  { days: 1, label: "24 hours" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];

const STAGES = [
  { key: "self", label: "Self-check", line: "Deterministic, inside each agent: the result parsed, the status is not failed, and an ok answer cites evidence." },
  { key: "independent", label: "Independent review", line: "The Groq judge, a different model from the agents, scores the answer against the subtask on a rubric." },
  { key: "evidence", label: "Evidence check", line: "Every evidence reference resolves to a database record, a GitHub response or a peer answer." },
];

const ACTION_WORD = { retry: "Retried with reviewer feedback", replan: "Asked the CEO to replan", clarify: "Asked for clarification", give_up: "Gave up" } as const;

function readJudge(payload: Record<string, unknown>): JudgeVerdict | null {
  const judge = payload.judge;
  return judge && typeof judge === "object" && Array.isArray((judge as JudgeVerdict).dimensions) ? (judge as JudgeVerdict) : null;
}

function readStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function FeedItem({ record }: { record: SelfEvalRecord }) {
  const reasons = readStrings(record.payload.reasons);
  const feedback = typeof record.payload.feedback === "string" ? record.payload.feedback : "";
  const judge = readJudge(record.payload);
  const recovery = record.kind === "recovery";
  return (
    <li className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-x-3 border-t border-line px-5 py-3.5 first:border-t-0">
      <span className="pt-0.5">
        {recovery ? (
          <span className={`inline-flex size-5 items-center justify-center rounded-md ${record.action === "give_up" ? "bg-warn-soft text-warn" : "bg-accent-soft text-accent"}`} role="img" aria-label="Recovery">
            <RotateCcw aria-hidden size={12} strokeWidth={2.2} />
          </span>
        ) : (
          <Mark state={record.passed === null ? "unknown" : record.passed ? "pass" : "fail"} />
        )}
      </span>
      <div className="min-w-0 space-y-1">
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm text-ink">
          <AgentName name={record.agent} />
          <span className="font-medium">{recovery ? ACTION_WORD[record.action ?? "retry"] : `${record.stage ?? "unknown"} ${record.passed === null ? "not reviewed" : record.passed ? "passed" : "failed"}`}</span>
          <span className="font-mono text-2xs text-muted">
            attempt {record.attempt}
            {record.score !== null ? `, score ${fmtScore(record.score)}` : ""}
          </span>
          <span className="ml-auto text-2xs text-faint">{formatRelative(record.created_at)}</span>
        </p>
        {reasons.length > 0 ? <p className="text-sm text-ink-2">{reasons.join(" ")}</p> : null}
        {feedback ? <p className="border-l-2 border-accent/50 pl-2.5 text-sm text-ink-2">{feedback}</p> : null}
        {judge && !record.passed ? (
          <details>
            <summary className="cursor-pointer text-xs text-muted hover:text-ink">Judge detail</summary>
            <div className="mt-2">
              <JudgeDetail judge={judge} compact />
            </div>
          </details>
        ) : null}
        <p className="text-xs text-muted">
          {record.conversation_id ? (
            <a href={chatHref(record.conversation_id)} className="inline-flex items-center gap-0.5 font-medium text-ink-2 hover:text-ink">
              Open the conversation
              <ArrowUpRight aria-hidden size={12} strokeWidth={2} />
            </a>
          ) : (
            "No conversation recorded"
          )}{" "}
          <span className="font-mono text-2xs text-faint">{record.request_id}</span>
        </p>
      </div>
    </li>
  );
}

export function SelfEvalView() {
  const [days, setDays] = useState(7);
  const [stats, reload] = useEvals((client, signal) => client.getSelfEval(days, signal), `evals-self-${days}`);
  const s = stats.data;

  return (
    <div className="space-y-5">
      <section className="card space-y-5 p-5 sm:p-6" aria-labelledby="self-eval">
        <SectionHead
          id="self-eval"
          title="Live self-evaluation"
          actions={
            <div role="radiogroup" aria-label="Time window" className="flex gap-1 rounded-block bg-subtle p-1">
              {WINDOWS.map((w) => (
                <button
                  key={w.days}
                  type="button"
                  role="radio"
                  aria-checked={days === w.days}
                  onClick={() => setDays(w.days)}
                  className={`h-7 rounded-[7px] px-3 text-xs transition-colors ${days === w.days ? "bg-surface font-medium text-ink shadow-card" : "text-muted hover:text-ink"}`}
                >
                  {w.label}
                </button>
              ))}
            </div>
          }
        >
          Every department answer in real chat requests is reviewed before the CEO uses it. A failed review can send the agent back once with the reviewer's feedback.
        </SectionHead>

        {stats.status === "loading" && !s ? <LoadingState label="Loading self-evaluation" lines={4} /> : null}
        {stats.status === "error" && !s ? <ErrorState title="Could not load self-evaluation" detail={stats.error} onRetry={reload} /> : null}
        {s && s.evaluations === 0 ? (
          <EmptyState title="No reviews in this window" icon={<ShieldCheck size={20} strokeWidth={1.75} />}>
            Ask a question in the chat; each agent result is reviewed as it arrives.
          </EmptyState>
        ) : null}
        {s && s.evaluations > 0 ? <Stats s={s} /> : null}
      </section>

      {s && s.recent.length > 0 ? (
        <section className="card overflow-hidden" aria-labelledby="feed">
          <div className="border-b border-line px-5 py-4">
            <SectionHead id="feed" title="Recent reviews and recoveries">
              Newest first. Retries show the feedback the agent received.
            </SectionHead>
          </div>
          <ol>
            {s.recent.map((record, i) => (
              <FeedItem key={`${record.request_id}-${i}`} record={record} />
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}

function Stats({ s }: { s: SelfEvalStats }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-x-6 gap-y-5 border-t border-line pt-5 sm:grid-cols-4">
        <Figure value={String(s.evaluations)} label="Reviews" note={`Last ${s.window_days === 1 ? "24 hours" : `${s.window_days} days`}`} />
        <Figure value={String(s.retries)} label="Retries" note="Agents sent back with feedback" />
        <Figure value={pct(s.retry_success_rate)} label="Retry success" note="Retries that passed review" />
        <Figure value={String(s.judge_errors)} label="Judge errors" note="Reviews the judge could not complete" />
      </div>
      <ul className="space-y-4 border-t border-line pt-5">
        {STAGES.map((stage) => {
          const value = s.by_stage[stage.key];
          return (
            <li key={stage.key} className="grid gap-x-8 gap-y-2 md:grid-cols-[minmax(0,1fr)_minmax(0,18rem)_3rem] md:items-center">
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink">
                  {stage.label} <span className="font-mono text-2xs font-normal text-faint">{stage.key}</span>
                </p>
                <p className="text-xs text-muted">{stage.line}</p>
              </div>
              <Meter value={value ?? null} label={`${stage.label} pass rate`} tone={value !== undefined && value < 0.8 ? "bg-warn" : "bg-ink-2"} />
              <p className="text-sm font-medium text-ink tabular-nums md:text-right">{pct(value)}</p>
            </li>
          );
        })}
      </ul>
    </>
  );
}
