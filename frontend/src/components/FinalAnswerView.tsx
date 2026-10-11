import { AlertTriangle, ExternalLink } from "lucide-react";
import { memo, useMemo, useState } from "react";
import type { FinalOutcome } from "../lib/run";
import type { AgentResult, Claim, Evidence } from "../types/contracts";
import { agentLabel } from "../lib/agents";
import { AgentAvatar, AgentName } from "./AgentName";
import { EvidenceItem } from "./EvidenceItem";
import { RichText } from "./RichText";
import { RunStateLabel } from "./RunStatus";

interface IndexedEvidence {
  evidence: Evidence;
  agent: string;
}

function indexEvidence(results: AgentResult[]): Map<string, IndexedEvidence> {
  const index = new Map<string, IndexedEvidence>();
  for (const result of results) {
    for (const evidence of result.evidence) {
      if (!index.has(evidence.source_ref)) index.set(evidence.source_ref, { evidence, agent: result.agent });
    }
  }
  return index;
}

/** a, b, ... z, aa, ab: footnote letters so they never collide with the claim numbers. */
function footnoteLetter(position: number): string {
  let n = position;
  let letters = "";
  do {
    letters = String.fromCharCode(97 + (n % 26)) + letters;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return letters;
}

/** Letters are assigned in order of first citation across the whole answer. */
function letterRefs(claims: Claim[]): Map<string, string> {
  const letters = new Map<string, string>();
  for (const claim of claims) {
    for (const ref of claim.evidence_refs) {
      if (!letters.has(ref)) letters.set(ref, footnoteLetter(letters.size));
    }
  }
  return letters;
}

function joinNames(names: string[]): string {
  const labels = names.map(agentLabel);
  if (labels.length <= 1) return labels.join("");
  return `${labels.slice(0, -1).join(", ")} and ${labels.at(-1)}`;
}

interface ClaimRowProps {
  claim: Claim;
  number: number;
  index: Map<string, IndexedEvidence>;
  letters: Map<string, string>;
}

function ClaimRow({ claim, number, index, letters }: ClaimRowProps) {
  const [open, setOpen] = useState(false);
  const refs = claim.evidence_refs;
  const markers = refs.map((ref) => letters.get(ref) ?? "?");

  return (
    <li className="flex gap-3 border-t border-line px-5 py-4 first:border-t-0">
      <span className="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-subtle text-xs font-medium text-ink-2">
        {number}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-read text-ink">{claim.text}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {claim.agents.map((agent) => (
            <span key={agent} className="inline-flex items-center gap-1.5 text-xs text-muted">
              <AgentAvatar name={agent} size="sm" />
            </span>
          ))}
          {claim.agents.length > 0 ? <span className="text-xs text-muted">From {joinNames(claim.agents)}</span> : null}
          {refs.length > 0 ? (
            <button
              type="button"
              aria-expanded={open}
              aria-label={`${open ? "Hide" : "Show"} ${refs.length} ${refs.length === 1 ? "source" : "sources"} for finding ${number}`}
              onClick={() => setOpen((value) => !value)}
              className={`chip ml-auto cursor-pointer font-mono transition-colors ${
                open ? "bg-accent text-surface" : "bg-accent-soft text-accent-strong hover:bg-accent/20"
              }`}
            >
              {refs.length} {refs.length === 1 ? "source" : "sources"}
              <span className="opacity-70">{markers.join(",")}</span>
            </button>
          ) : (
            <span className="chip ml-auto bg-warn-soft text-warn">No evidence cited</span>
          )}
        </div>
        {open ? (
          <ul className="mt-3 space-y-4 rounded-block bg-subtle p-4">
            {refs.map((ref) => {
              const hit = index.get(ref);
              const marker = letters.get(ref) ?? "?";
              if (hit) return <EvidenceItem key={ref} evidence={hit.evidence} agent={hit.agent} marker={marker} />;
              return (
                <li key={ref} className="flex gap-3 text-sm text-warn">
                  <span className="font-mono text-2xs">{marker}</span>
                  <span>
                    This reference is not in any agent's evidence:{" "}
                    <code className="font-mono text-2xs break-all">{ref}</code>
                  </span>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </li>
  );
}

interface FinalAnswerViewProps {
  outcome: FinalOutcome;
  traceUrl: string | null;
}

export const FinalAnswerView = memo(function FinalAnswerView({ outcome, traceUrl }: FinalAnswerViewProps) {
  const { answer, results } = outcome;
  const index = useMemo(() => indexEvidence(results), [results]);
  const letters = useMemo(() => letterRefs(answer.claims), [answer.claims]);
  const troubled = results.filter((result) => result.status !== "ok");
  const sourceCount = letters.size;

  return (
    <div className="space-y-4 animate-enter">
      <div className="card p-5">
        <p className="max-w-[68ch] text-read text-ink">
          <RichText text={answer.answer} />
        </p>
        <div className="mt-4 border-t border-line pt-3">
          <TraceLink url={traceUrl} />
        </div>
      </div>

      {answer.claims.length > 0 ? (
        <section aria-labelledby="findings-heading" className="card overflow-hidden">
          <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
            <h3 id="findings-heading" className="text-base font-medium text-ink">
              Findings
            </h3>
            <span className="text-xs text-muted">
              {answer.claims.length} {answer.claims.length === 1 ? "finding" : "findings"}, {sourceCount}{" "}
              {sourceCount === 1 ? "source" : "sources"}
            </span>
          </header>
          <ol>
            {answer.claims.map((claim, i) => (
              <ClaimRow key={`${i}-${claim.text.slice(0, 24)}`} claim={claim} number={i + 1} index={index} letters={letters} />
            ))}
          </ol>
        </section>
      ) : null}

      {answer.unanswered.length > 0 || troubled.length > 0 ? (
        <section aria-labelledby="gaps-heading" className="rounded-card border border-warn/25 bg-warn-soft p-5">
          <h3 id="gaps-heading" className="flex items-center gap-2 text-base font-medium text-warn">
            <AlertTriangle aria-hidden size={16} strokeWidth={1.75} />
            Not answered
          </h3>
          {answer.unanswered.length > 0 ? (
            <ul className="mt-2 space-y-1.5 text-sm leading-relaxed text-ink-2">
              {answer.unanswered.map((item) => (
                <li key={item}>
                  <RichText text={item} />
                </li>
              ))}
            </ul>
          ) : null}
          {troubled.length > 0 ? (
            <ul className="mt-3 space-y-2 text-sm">
              {troubled.map((result) => (
                <li key={`${result.agent}-${result.subtask_id}`} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <AgentName name={result.agent} />
                  <RunStateLabel state={result.status} />
                  {result.error ? <span className="text-ink-2">{result.error}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
});

export function TraceLink({ url }: { url: string | null }) {
  if (!url) return <p className="text-xs text-faint">No Langfuse trace was recorded for this request.</p>;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 text-xs font-medium text-muted transition-colors hover:text-ink"
    >
      View the trace in Langfuse
      <ExternalLink aria-hidden size={12} strokeWidth={2} />
    </a>
  );
}
