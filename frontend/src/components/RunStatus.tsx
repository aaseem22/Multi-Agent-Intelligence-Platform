import type { AgentRunState } from "../lib/run";

const LABELS: Record<AgentRunState, string> = {
  queued: "Queued",
  running: "Working",
  ok: "Done",
  partial: "Partial",
  failed: "Failed",
  needs_clarification: "Needs clarification",
};

const TONE: Record<AgentRunState, string> = {
  queued: "bg-subtle text-muted",
  running: "bg-accent-soft text-accent-strong",
  ok: "bg-ok-soft text-ok",
  partial: "bg-warn-soft text-warn",
  failed: "bg-danger-soft text-danger",
  needs_clarification: "bg-warn-soft text-warn",
};

const DOT: Record<AgentRunState, string> = {
  queued: "bg-faint",
  running: "live-dot",
  ok: "bg-ok",
  partial: "bg-warn",
  failed: "bg-danger",
  needs_clarification: "bg-warn",
};

/** Status as a small pill: a dot that pulses while the agent works, and a word. */
export function RunStateLabel({ state }: { state: AgentRunState }) {
  return (
    <span className={`chip ${TONE[state]}`}>
      <span aria-hidden className={`size-1.5 rounded-full ${DOT[state]}`} />
      {LABELS[state]}
    </span>
  );
}
