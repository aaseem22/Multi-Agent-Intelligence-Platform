import type { Evidence, EvidenceSourceType } from "../types/contracts";
import { AgentName } from "./AgentName";

const SOURCE_LABEL: Record<EvidenceSourceType, string> = {
  db: "Database record",
  github: "GitHub API response",
  peer: "Answer from a peer agent",
};

interface EvidenceItemProps {
  evidence: Evidence;
  agent: string;
  marker: string;
}

/** One footnote: its letter hangs in the margin, the reference is set in mono so it can be copied. */
export function EvidenceItem({ evidence, agent, marker }: EvidenceItemProps) {
  const hasData = evidence.data !== null && Object.keys(evidence.data).length > 0;
  return (
    <li className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-x-1 animate-enter">
      <span className="pt-0.5 font-mono text-2xs text-pencil">{marker}</span>
      <div className="min-w-0">
        <p className="text-sm text-ink">{evidence.summary}</p>
        <p className="text-2xs text-graphite">
          {SOURCE_LABEL[evidence.source_type]}, cited by <AgentName name={agent} />
        </p>
        <code className="block font-mono text-2xs break-all text-graphite">{evidence.source_ref}</code>
        {hasData ? (
          <details className="group/raw mt-0.5">
            <summary className="cursor-pointer text-2xs text-pencil hover:text-ink">
              <span aria-hidden className="mr-1 inline-block font-mono transition-transform group-open/raw:rotate-90">
                ›
              </span>
              Raw excerpt
            </summary>
            <pre className="mt-1 max-h-48 overflow-auto border-l border-rule py-1 pl-3 font-mono text-2xs text-ink">
              {JSON.stringify(evidence.data, null, 2)}
            </pre>
          </details>
        ) : null}
      </div>
    </li>
  );
}
