import { Check, CornerDownRight, X } from "lucide-react";
import type { AgentRun, EvalCheck, RecoveryRecord } from "../lib/run";
import { JudgeDetail } from "./JudgeDetail";

const STAGE_WORD: Record<EvalCheck["result"]["stage"], string> = { self: "self-check", independent: "judge", evidence: "evidence" };
const RECOVERY_WORD: Record<RecoveryRecord["action"], string> = {
  retry: "Retried with reviewer feedback",
  replan: "Sent back to the CEO to replan",
  clarify: "Asked for clarification",
  give_up: "Gave up after review",
};

function CheckWord({ check }: { check: EvalCheck }) {
  const { result } = check;
  const Icon = result.passed ? Check : X;
  return (
    <span
      className={`inline-flex items-center gap-0.5 ${result.passed ? "text-ink-2" : "font-medium text-danger"}`}
      title={result.reasons.join(" ") || undefined}
    >
      <Icon aria-label={result.passed ? "passed" : "failed"} size={11} strokeWidth={2.6} className={result.passed ? "text-ok" : "text-danger"} />
      {STAGE_WORD[result.stage]}
      {result.score !== null ? <span className="font-mono text-faint tabular-nums">{result.score.toFixed(2)}</span> : null}
    </span>
  );
}

/**
 * Live self-evaluation under each agent, set like a footnote: one line per attempt listing the
 * stages it passed, the router's action between attempts, and the judge's reasoning on demand.
 */
export function SelfReview({ run }: { run: AgentRun }) {
  if (run.evals.length === 0 && run.recoveries.length === 0) return null;
  const attempts = [...new Set([...run.evals.map((e) => e.attempt), ...run.recoveries.map((r) => r.attempt)])].sort((a, b) => a - b);
  const multiple = attempts.length > 1;

  return (
    <div aria-label="Self-evaluation" className="space-y-1 border-l border-line pl-2.5 text-2xs leading-5">
      {attempts.map((attempt) => {
        const checks = run.evals.filter((e) => e.attempt === attempt);
        const recovery = run.recoveries.filter((r) => r.attempt === attempt);
        const judged = checks.find((c) => c.judge && (!c.result.passed || c.judge.dimensions.some((d) => d.verdict !== "pass")));
        return (
          <div key={attempt} className="space-y-1">
            {checks.length > 0 ? (
              <p className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-muted">
                <span className="text-faint">{multiple ? `Reviewed, attempt ${attempt}` : "Reviewed"}</span>
                {checks.map((check, i) => (
                  <CheckWord key={`${check.result.stage}-${i}`} check={check} />
                ))}
              </p>
            ) : null}
            {judged?.judge ? (
              <details className="group/judge">
                <summary className="cursor-pointer text-muted transition-colors hover:text-ink">Why the judge {judged.result.passed ? "had doubts" : "failed it"}</summary>
                <div className="mt-1.5 mb-1 rounded-block bg-subtle p-2.5">
                  <JudgeDetail judge={judged.judge} compact />
                </div>
              </details>
            ) : null}
            {recovery.map((r, i) => (
              <div key={i} className="flex gap-1.5 text-ink-2">
                <CornerDownRight aria-hidden size={12} strokeWidth={2} className={`mt-1 shrink-0 ${r.action === "give_up" ? "text-warn" : "text-accent"}`} />
                <p className="min-w-0">
                  <span className={`font-medium ${r.action === "give_up" ? "text-warn" : "text-accent-strong"}`}>{RECOVERY_WORD[r.action]}</span>
                  {r.feedback ? <span className="text-muted">: &ldquo;{r.feedback}&rdquo;</span> : r.reasons.length ? <span className="text-muted">: {r.reasons.join("; ")}</span> : null}
                </p>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
