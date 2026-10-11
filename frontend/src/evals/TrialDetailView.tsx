import { ExternalLink, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { evalsClient } from "../api/evals";
import { JudgeDetail } from "../components/JudgeDetail";
import { RichText } from "../components/RichText";
import { ErrorState, LoadingState } from "../components/States";
import { evalsHref } from "../hooks/useHashRoute";
import { agentLabel } from "../lib/agents";
import { errorMessage, formatRelative } from "../lib/format";
import type { GraderResult, HumanLabel, TrialResult } from "../types/evals";
import { duration, fmtScore, humanise, KIND_COPY, trialState, useEvals } from "./lib";
import { Transcript } from "./Transcript";
import { Crumbs, Mark, SectionHead, Verdict } from "./ui";

function LabelControl({ runId, trialId, grader, existing, onSaved }: { runId: string; trialId: string; grader: GraderResult; existing: HumanLabel | undefined; onSaved: (label: HumanLabel) => void }) {
  const [note, setNote] = useState(existing?.note ?? "");
  const [saving, setSaving] = useState<"agree" | "disagree" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const agreed = existing ? existing.human_passed === grader.passed : null;

  const save = async (agree: boolean) => {
    setSaving(agree ? "agree" : "disagree");
    setError(null);
    try {
      const client = await evalsClient();
      const label = await client.putLabel(runId, { trial_id: trialId, grader: grader.grader, human_passed: agree ? grader.passed : !grader.passed, note: note.trim() || undefined });
      onSaved(label);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(null);
    }
  };

  const choice = (agree: boolean) => {
    const selected = agreed === agree;
    const Icon = agree ? ThumbsUp : ThumbsDown;
    return (
      <button
        type="button"
        onClick={() => save(agree)}
        disabled={saving !== null}
        aria-pressed={selected}
        className={`btn h-8 ${selected ? "btn-primary" : "btn-secondary"}`}
      >
        <Icon aria-hidden size={13} strokeWidth={1.9} />
        {saving === (agree ? "agree" : "disagree") ? "Saving" : agree ? "Agree" : "Disagree"}
      </button>
    );
  };

  return (
    <div className="space-y-2 rounded-block border border-dashed border-line-strong p-3">
      <p className="text-sm text-ink">
        Do you agree that this should <span className="font-semibold">{grader.passed ? "pass" : "fail"}</span>?
        <span className="block text-xs text-muted">Your verdict calibrates the judge. It does not change this trial's score.</span>
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {choice(true)}
        {choice(false)}
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Optional note, e.g. what the judge missed"
          aria-label={`Note for ${grader.grader}`}
          className="h-8 min-w-0 flex-1 basis-56 rounded-block border border-line bg-surface px-2.5 text-sm text-ink placeholder:text-faint"
        />
      </div>
      {existing ? (
        <p className="text-xs text-muted">
          Labelled {formatRelative(existing.labelled_at)}: you said it should {existing.human_passed ? "pass" : "fail"}
          {agreed ? ", agreeing with the judge" : ", disagreeing with the judge"}.{existing.note ? ` Note: ${existing.note}` : ""}
        </p>
      ) : null}
      {error ? <p className="text-xs text-danger">Could not save: {error}</p> : null}
    </div>
  );
}

function GraderItem({ grader, runId, trialId, label, onSaved }: { grader: GraderResult; runId: string; trialId: string; label: HumanLabel | undefined; onSaved: (l: HumanLabel) => void }) {
  return (
    <li className="space-y-3 border-t border-line px-5 py-4 first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Mark state={grader.passed ? "pass" : "fail"} />
        <span className="text-base font-medium text-ink">{humanise(grader.grader)}</span>
        <span className="text-xs text-muted">{grader.kind === "model" ? "model grader" : grader.kind === "human" ? "human grader" : "code grader"}</span>
        <span className="ml-auto font-mono text-xs text-muted tabular-nums">
          score {fmtScore(grader.score)}, weight {grader.weight}
        </span>
      </div>
      {grader.kind !== "model" && grader.reasons.length > 0 ? (
        <ul className="list-disc space-y-0.5 pl-9 text-sm text-ink-2">
          {grader.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : null}
      {grader.judge ? (
        <div className="pl-8">
          <JudgeDetail judge={grader.judge} />
        </div>
      ) : grader.kind === "model" && grader.reasons.length > 0 ? (
        <p className="pl-8 text-sm text-ink-2">{grader.reasons.join(" ")}</p>
      ) : null}
      {grader.kind === "model" ? (
        <div className="pl-8">
          <LabelControl key={label?.labelled_at ?? "none"} runId={runId} trialId={trialId} grader={grader} existing={label} onSaved={onSaved} />
        </div>
      ) : null}
    </li>
  );
}

function Outcome({ trial }: { trial: TrialResult }) {
  if (trial.error) return <ErrorState title="The trial errored before it could be graded" detail={trial.error} />;
  if (trial.clarification) {
    return (
      <div className="space-y-1">
        <p className="text-xs text-muted">The CEO asked back instead of answering</p>
        <p className="max-w-[68ch] text-read text-ink">{trial.clarification}</p>
      </div>
    );
  }
  if (trial.final_answer) {
    return (
      <div className="space-y-1">
        <p className="text-xs text-muted">Final answer</p>
        <p className="max-w-[68ch] text-read text-ink">
          <RichText text={trial.final_answer} />
        </p>
      </div>
    );
  }
  return <p className="text-sm text-muted">No answer was recorded.</p>;
}

export function TrialDetailView({ runId, trialId }: { runId: string; trialId: string }) {
  const [trial, reload] = useEvals((client, signal) => client.getTrial(runId, trialId, signal), `evals-trial-${runId}-${trialId}`);
  const [labels] = useEvals((client, signal) => client.getLabels(runId, signal), `evals-labels-${runId}`);
  const [saved, setSaved] = useState<Record<string, HumanLabel>>({});

  const crumbs = (
    <Crumbs
      items={[
        { href: evalsHref({ kind: "runs" }), label: "Runs" },
        { href: evalsHref({ kind: "run", runId }), label: runId },
        { label: trialId },
      ]}
    />
  );
  if (trial.status === "loading" && !trial.data) {
    return (
      <div className="space-y-4">
        {crumbs}
        <div className="card p-6">
          <LoadingState label="Loading trial" lines={6} />
        </div>
      </div>
    );
  }
  if (trial.status === "error" && !trial.data) {
    return (
      <div className="space-y-4">
        {crumbs}
        <ErrorState title="Could not load this trial" detail={trial.error} onRetry={reload} />
      </div>
    );
  }
  const t = trial.data as TrialResult;
  const labelFor = (grader: string) => saved[grader] ?? labels.data?.find((l) => l.trial_id === t.trial_id && l.grader === grader);
  const codeGraders = t.graders.filter((g) => g.kind !== "model");
  const modelGraders = t.graders.filter((g) => g.kind === "model");
  const onSaved = (label: HumanLabel) => setSaved((current) => ({ ...current, [label.grader]: label }));

  return (
    <div className="space-y-5">
      {crumbs}
      <section className="card space-y-5 p-5 sm:p-6" aria-labelledby="trial-question">
        <div className="space-y-2">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
            <span className="font-mono text-xs text-ink">{t.task_id}</span>
            <span>Trial {t.index + 1}</span>
            <Verdict state={trialState(t)}>
              {t.status === "passed" ? "Passed" : t.status === "error" ? "Error" : "Failed"}, score {fmtScore(t.score)}
            </Verdict>
          </p>
          <h2 id="trial-question" className="max-w-[60ch] text-xl leading-snug font-semibold tracking-tight text-ink">
            {t.question}
          </h2>
        </div>
        <Outcome trial={t} />
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line pt-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Agents planned", t.agents_planned.length ? t.agents_planned.map(agentLabel).join(", ") : "None"],
            ["Peer requests", String(t.peer_requests)],
            ["Refusals", String(t.refusals)],
            ["Self-eval retries", String(t.recoveries)],
            ["LLM calls", String(t.llm_calls)],
            ["Duration", duration(t.duration_ms)],
          ].map(([term, value]) => (
            <div key={term}>
              <dt className="text-xs text-muted">{term}</dt>
              <dd className="mt-0.5 text-ink tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        {t.trace_url ? (
          <a href={t.trace_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-xs font-medium text-muted transition-colors hover:text-ink">
            View the trace in Langfuse
            <ExternalLink aria-hidden size={12} strokeWidth={2} />
          </a>
        ) : null}
      </section>

      {t.graders.length > 0 ? (
        <div className="space-y-5">
          {[
            { kind: "code" as const, list: codeGraders },
            { kind: "model" as const, list: modelGraders },
          ]
            .filter((group) => group.list.length > 0)
            .map((group) => (
              <section key={group.kind} className="card overflow-hidden" aria-labelledby={`g-${group.kind}`}>
                <div className="border-b border-line px-5 py-4">
                  <SectionHead id={`g-${group.kind}`} title={KIND_COPY[group.kind].label}>
                    {KIND_COPY[group.kind].line}
                  </SectionHead>
                </div>
                <ul>
                  {group.list.map((g) => (
                    <GraderItem key={g.grader} grader={g} runId={runId} trialId={t.trial_id} label={labelFor(g.grader)} onSaved={onSaved} />
                  ))}
                </ul>
              </section>
            ))}
        </div>
      ) : null}

      <section className="card space-y-4 p-5" aria-labelledby="transcript">
        <SectionHead id="transcript" title="Transcript">
          Every event the trial streamed, in order. Read it to tell a real agent mistake from a grader that rejected a valid answer: failures should look fair.
        </SectionHead>
        <Transcript events={t.transcript} />
      </section>
    </div>
  );
}
