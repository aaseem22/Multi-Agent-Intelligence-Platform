import { CheckCircle2, CircleDashed, CircleHelp, CircleSlash, CircleX, LoaderCircle } from "lucide-react";
import type { AgentRunState } from "../lib/run";

const LABELS: Record<AgentRunState, string> = {
  queued: "Queued",
  running: "Working",
  ok: "Done",
  partial: "Partial",
  failed: "Failed",
  needs_clarification: "Needs clarification",
};

export function RunStateIcon({ state }: { state: AgentRunState }) {
  const common = "size-4 shrink-0";
  switch (state) {
    case "queued":
      return <CircleDashed aria-hidden className={`${common} text-faint`} />;
    case "running":
      return <LoaderCircle aria-hidden className={`${common} animate-spin text-agent-tech`} />;
    case "ok":
      return <CheckCircle2 aria-hidden className={`${common} text-ok`} />;
    case "partial":
      return <CircleSlash aria-hidden className={`${common} text-warn`} />;
    case "failed":
      return <CircleX aria-hidden className={`${common} text-fail`} />;
    case "needs_clarification":
      return <CircleHelp aria-hidden className={`${common} text-warn`} />;
  }
}

const TEXT_TONE: Record<AgentRunState, string> = {
  queued: "text-faint",
  running: "text-agent-tech",
  ok: "text-ok",
  partial: "text-warn",
  failed: "text-fail",
  needs_clarification: "text-warn",
};

export function RunStateLabel({ state }: { state: AgentRunState }) {
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${TEXT_TONE[state]}`}>
      <RunStateIcon state={state} />
      {LABELS[state]}
    </span>
  );
}
