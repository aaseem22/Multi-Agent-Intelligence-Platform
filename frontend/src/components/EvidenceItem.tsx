import { Braces, Database, FolderGit2, MessageSquareShare } from "lucide-react";
import type { Evidence, EvidenceSourceType } from "../types/contracts";
import { AgentBadge } from "./AgentBadge";

const SOURCE: Record<EvidenceSourceType, { label: string; icon: typeof Database }> = {
  db: { label: "Database record", icon: Database },
  github: { label: "GitHub API", icon: FolderGit2 },
  peer: { label: "Peer answer", icon: MessageSquareShare },
};

interface EvidenceItemProps {
  evidence: Evidence;
  agent: string;
}

export function EvidenceItem({ evidence, agent }: EvidenceItemProps) {
  const source = SOURCE[evidence.source_type];
  const Icon = source.icon;
  return (
    <li className="rounded-md border border-line bg-paper/60 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <Icon aria-hidden className="size-3.5" />
        <span>{source.label}</span>
        <span aria-hidden className="text-line">|</span>
        <span>cited by</span>
        <AgentBadge name={agent} />
      </div>
      <p className="mt-1 text-sm text-ink">{evidence.summary}</p>
      <code className="mt-1 block font-mono text-xs break-all text-muted">{evidence.source_ref}</code>
      {evidence.data && Object.keys(evidence.data).length > 0 ? (
        <details className="mt-1.5">
          <summary className="inline-flex cursor-pointer items-center gap-1 text-xs text-muted hover:text-ink">
            <Braces aria-hidden className="size-3" />
            Raw excerpt
          </summary>
          <pre className="mt-1 max-h-48 overflow-auto rounded bg-surface p-2 font-mono text-xs text-ink">
            {JSON.stringify(evidence.data, null, 2)}
          </pre>
        </details>
      ) : null}
    </li>
  );
}
