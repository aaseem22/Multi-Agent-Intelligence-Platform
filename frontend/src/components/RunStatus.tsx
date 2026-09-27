import type { AgentRunState } from "../lib/run";

const LABELS: Record<AgentRunState, string> = {
  queued: "queued",
  running: "working",
  ok: "done",
  partial: "partial",
  failed: "failed",
  needs_clarification: "needs clarification",
};

// Typographic glyphs rather than icons: they sit on the baseline like the words beside them.
const GLYPHS: Record<AgentRunState, string> = {
  queued: "○",
  running: "◐",
  ok: "●",
  partial: "◑",
  failed: "✕",
  needs_clarification: "?",
};

const INK: Record<AgentRunState, string> = {
  queued: "text-pencil",
  running: "text-ink",
  ok: "text-done",
  partial: "text-caution",
  failed: "text-refuse",
  needs_clarification: "text-caution",
};

/** Status as a word with a small glyph. "Working" gets the highlighter because it is what is happening now. */
export function RunStateLabel({ state }: { state: AgentRunState }) {
  return (
    <span className={`inline-flex items-baseline gap-1.5 text-xs whitespace-nowrap ${INK[state]}`}>
      <span aria-hidden className={`font-mono ${state === "running" ? "animate-breathe" : ""}`}>
        {GLYPHS[state]}
      </span>
      <span className={state === "running" ? "marked" : ""}>{LABELS[state]}</span>
    </span>
  );
}
