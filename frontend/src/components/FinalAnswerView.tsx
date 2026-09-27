import { ChevronDown, CircleAlert, ExternalLink } from "lucide-react";
import { memo, useMemo, useState } from "react";
import type { FinalOutcome } from "../lib/run";
import type { AgentResult, Claim, Evidence } from "../types/contracts";
import { AgentBadge } from "./AgentBadge";
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

function ClaimRow({ claim, index }: { claim: Claim; index: Map<string, IndexedEvidence> }) {
  const [open, setOpen] = useState(false);
  const refs = claim.evidence_refs;
  const found = refs.flatMap((ref) => {
    const hit = index.get(ref);
    return hit ? [hit] : [];
  });
  const missing = refs.filter((ref) => !index.has(ref));

  return (
    <li className="py-2.5">
      <div className="flex items-start gap-3">
        <p className="min-w-0 flex-1 text-[15px] leading-relaxed">{claim.text}</p>
        {refs.length > 0 ? (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line px-2 py-1 text-xs font-medium text-muted hover:border-agent-tech/50 hover:text-ink"
          >
            {refs.length} {refs.length === 1 ? "source" : "sources"}
            <ChevronDown aria-hidden className={`size-3 transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
        ) : (
          <span className="shrink-0 rounded-md bg-warn/10 px-2 py-1 text-xs font-medium text-warn">No evidence cited</span>
        )}
      </div>
      {claim.agents.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {claim.agents.map((agent) => (
            <AgentBadge key={agent} name={agent} />
          ))}
        </div>
      ) : null}
      {open ? (
        <ul className="mt-2 space-y-1.5 animate-enter">
          {found.map((item) => (
            <EvidenceItem key={item.evidence.source_ref} evidence={item.evidence} agent={item.agent} />
          ))}
          {missing.map((ref) => (
            <li key={ref} className="rounded-md border border-warn/40 bg-warn/5 px-3 py-2 text-xs text-warn">
              Cited reference not found in any agent result: <code className="font-mono break-all">{ref}</code>
            </li>
          ))}
        </ul>
      ) : null}
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
  const troubled = results.filter((result) => result.status !== "ok");

  return (
    <div className="space-y-3">
      <p className="max-w-[72ch] text-[15px] leading-relaxed whitespace-pre-line">{answer.answer}</p>

      {answer.claims.length > 0 ? (
        <section aria-label="Claims and evidence" className="rounded-lg border border-line bg-surface px-3">
          <ul className="divide-y divide-line">
            {answer.claims.map((claim, i) => (
              <ClaimRow key={`${i}-${claim.text.slice(0, 24)}`} claim={claim} index={index} />
            ))}
          </ul>
        </section>
      ) : null}

      {answer.unanswered.length > 0 ? (
        <section aria-label="Not answered" className="rounded-lg border border-warn/40 bg-warn/5 px-3 py-2.5">
          <p className="flex items-center gap-1.5 text-sm font-medium text-warn">
            <CircleAlert aria-hidden className="size-4" />
            Could not be answered
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-6 text-sm text-ink/85">
            {answer.unanswered.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {troubled.length > 0 ? (
        <ul className="space-y-1 text-sm">
          {troubled.map((result) => (
            <li key={`${result.agent}-${result.subtask_id}`} className="flex flex-wrap items-center gap-2">
              <AgentBadge name={result.agent} />
              <RunStateLabel state={result.status} />
              {result.error ? <span className="text-muted">{result.error}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}

      <TraceLink url={traceUrl} />
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
      className="inline-flex items-center gap-1 text-xs font-medium text-agent-tech hover:underline"
    >
      <ExternalLink aria-hidden className="size-3" />
      Open trace in Langfuse
    </a>
  );
}
