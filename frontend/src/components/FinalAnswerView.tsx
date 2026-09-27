import { memo, useMemo, useState } from "react";
import type { FinalOutcome } from "../lib/run";
import type { AgentResult, Claim, Evidence } from "../types/contracts";
import { agentLabel } from "../lib/agents";
import { AgentName } from "./AgentName";
import { EvidenceItem } from "./EvidenceItem";
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

/** Letters are assigned in order of first citation across the whole answer, like footnotes in a memo. */
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
    <li className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-1 py-2">
      <span className="pt-[0.2rem] text-sm text-pencil">{number}.</span>
      <div className="min-w-0">
        <p className="text-read">
          {claim.text}
          {refs.length > 0 ? (
            <button
              type="button"
              aria-expanded={open}
              aria-label={`${open ? "Hide" : "Show"} ${refs.length} ${refs.length === 1 ? "source" : "sources"} for finding ${number}`}
              onClick={() => setOpen((value) => !value)}
              className={`ml-1 rounded-xs px-0.5 align-super font-mono text-xs leading-none text-graphite underline decoration-dotted underline-offset-2 hover:text-ink ${
                open ? "marked text-ink" : ""
              }`}
            >
              {markers.join(",")}
            </button>
          ) : (
            <span className="ml-2 text-xs text-caution italic">no evidence cited</span>
          )}
        </p>
        {claim.agents.length > 0 ? (
          <p className="text-xs text-graphite italic">From {joinNames(claim.agents)}.</p>
        ) : null}
        {open ? (
          <ul className="mt-2 mb-1 space-y-2.5 border-l border-rule-strong pl-3">
            {refs.map((ref) => {
              const hit = index.get(ref);
              const marker = letters.get(ref) ?? "?";
              if (hit) return <EvidenceItem key={ref} evidence={hit.evidence} agent={hit.agent} marker={marker} />;
              return (
                <li key={ref} className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-x-1 text-xs text-caution">
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

  return (
    <div className="space-y-6">
      <p className="max-w-[66ch] text-read whitespace-pre-line">{answer.answer}</p>

      {answer.claims.length > 0 ? (
        <section aria-labelledby="findings-heading" className="max-w-[70ch]">
          <h3 id="findings-heading" className="border-b border-rule pb-1 text-sm font-semibold text-graphite">
            Findings, with sources
          </h3>
          <ol>
            {answer.claims.map((claim, i) => (
              <ClaimRow
                key={`${i}-${claim.text.slice(0, 24)}`}
                claim={claim}
                number={i + 1}
                index={index}
                letters={letters}
              />
            ))}
          </ol>
        </section>
      ) : null}

      {answer.unanswered.length > 0 || troubled.length > 0 ? (
        <section aria-labelledby="gaps-heading" className="max-w-[70ch] border-l-2 border-caution pl-4">
          <h3 id="gaps-heading" className="text-sm font-semibold text-caution">
            Not answered
          </h3>
          {answer.unanswered.length > 0 ? (
            <ul className="mt-1 space-y-1 text-sm text-ink">
              {answer.unanswered.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
          {troubled.length > 0 ? (
            <ul className="mt-2 space-y-0.5 text-sm">
              {troubled.map((result) => (
                <li key={`${result.agent}-${result.subtask_id}`} className="flex flex-wrap items-baseline gap-x-2">
                  <AgentName name={result.agent} />
                  <RunStateLabel state={result.status} />
                  {result.error ? <span className="text-graphite">{result.error}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      <TraceLink url={traceUrl} />
    </div>
  );
});

export function TraceLink({ url }: { url: string | null }) {
  if (!url) return <p className="text-xs text-pencil italic">No Langfuse trace was recorded for this request.</p>;
  return (
    <p className="text-xs text-graphite">
      <a href={url} target="_blank" rel="noreferrer" className="link text-ink">
        Open the Langfuse trace
      </a>{" "}
      <span className="text-pencil">(new tab)</span>
    </p>
  );
}
