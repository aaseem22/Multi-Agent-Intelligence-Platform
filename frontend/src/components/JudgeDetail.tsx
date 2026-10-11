import { AlertTriangle, Check, HelpCircle, X } from "lucide-react";
import type { JudgeVerdict, Verdict } from "../types/evals";

const VERDICT: Record<Verdict, { icon: typeof Check; tone: string; word: string }> = {
  pass: { icon: Check, tone: "text-ok", word: "pass" },
  fail: { icon: X, tone: "text-danger", word: "fail" },
  unknown: { icon: HelpCircle, tone: "text-muted", word: "unknown" },
};

/** The judge's verdict per rubric dimension, with its reasoning. Compact enough for the chat run view. */
export function JudgeDetail({ judge, compact = false }: { judge: JudgeVerdict; compact?: boolean }) {
  return (
    <div className="space-y-2">
      {judge.error ? (
        <p className="flex items-start gap-1.5 text-xs text-warn">
          <AlertTriangle aria-hidden size={13} strokeWidth={1.75} className="mt-0.5 shrink-0" />
          Judge error: {judge.error}
        </p>
      ) : null}
      <ul className={compact ? "space-y-1" : "divide-y divide-line"}>
        {judge.dimensions.map((d) => {
          const v = VERDICT[d.verdict];
          const Icon = v.icon;
          return (
            <li key={d.dimension} className={`grid grid-cols-[1rem_minmax(0,1fr)_auto] gap-x-2 ${compact ? "text-xs" : "py-2 text-sm"}`}>
              <Icon aria-label={v.word} size={compact ? 12 : 14} strokeWidth={2.2} className={`mt-0.5 ${v.tone}`} />
              <div className="min-w-0">
                <span className="font-medium text-ink">{d.dimension.replace(/_/g, " ")}</span>{" "}
                <span className={`${v.tone} ${compact ? "" : "text-xs"}`}>{v.word}</span>
                <p className={`text-ink-2 ${compact ? "" : "mt-0.5"}`}>{d.reasoning}</p>
              </div>
              <span className="font-mono text-2xs text-muted tabular-nums">{d.score.toFixed(2)}</span>
            </li>
          );
        })}
      </ul>
      {judge.feedback ? (
        <p className={`border-l-2 border-line-strong pl-2.5 text-ink-2 ${compact ? "text-xs" : "text-sm"}`}>
          <span className="text-muted">Judge feedback: </span>
          {judge.feedback}
        </p>
      ) : null}
      <p className="font-mono text-2xs text-faint">
        {judge.rubric} rubric, {judge.model}
        {judge.score !== null ? `, score ${judge.score.toFixed(2)}` : ""}
      </p>
    </div>
  );
}
