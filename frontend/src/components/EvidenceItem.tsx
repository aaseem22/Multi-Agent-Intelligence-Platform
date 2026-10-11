import { ChevronRight, Database, GitBranch, MessagesSquare, type LucideIcon } from "lucide-react";
import type { Evidence, EvidenceSourceType } from "../types/contracts";
import { AgentName } from "./AgentName";

const SOURCE: Record<EvidenceSourceType, { label: string; icon: LucideIcon }> = {
  db: { label: "Database record", icon: Database },
  github: { label: "GitHub API response", icon: GitBranch },
  peer: { label: "Answer from a peer agent", icon: MessagesSquare },
};

interface EvidenceItemProps {
  evidence: Evidence;
  agent: string;
  marker: string;
}

/** One source: its footnote letter, what it shows, where it came from, and the copyable reference. */
export function EvidenceItem({ evidence, agent, marker }: EvidenceItemProps) {
  const hasData = evidence.data !== null && Object.keys(evidence.data).length > 0;
  const source = SOURCE[evidence.source_type];
  const Icon = source.icon;
  return (
    <li className="flex gap-3 animate-enter">
      <span className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-md bg-surface font-mono text-2xs font-medium text-ink-2 ring-1 ring-line">
        {marker}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm leading-relaxed text-ink">{evidence.summary}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-muted">
          <span className="inline-flex items-center gap-1">
            <Icon aria-hidden size={12} strokeWidth={1.75} />
            {source.label}
          </span>
          <span aria-hidden className="text-line-strong">/</span>
          <span>
            cited by <AgentName name={agent} />
          </span>
        </p>
        <code className="mt-1.5 inline-block max-w-full rounded-md bg-surface px-1.5 py-0.5 font-mono text-2xs break-all text-ink-2 ring-1 ring-line">
          {evidence.source_ref}
        </code>
        {hasData ? (
          <details className="group/raw mt-1.5">
            <summary className="inline-flex cursor-pointer items-center gap-1 text-2xs text-muted transition-colors hover:text-ink">
              <ChevronRight aria-hidden size={12} strokeWidth={2} className="transition-transform duration-200 group-open/raw:rotate-90" />
              Raw excerpt
            </summary>
            <pre className="mt-1.5 max-h-48 overflow-auto rounded-md bg-surface p-2.5 font-mono text-2xs leading-relaxed text-ink-2 ring-1 ring-line">
              {JSON.stringify(evidence.data, null, 2)}
            </pre>
          </details>
        ) : null}
      </div>
    </li>
  );
}
