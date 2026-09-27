import { ArrowRight, Ban, Network } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { agentLabel, agentTone } from "../lib/agents";
import { formatTime } from "../lib/format";
import type { FeedMessage, Turn } from "../lib/run";
import type { A2AMessageType } from "../types/contracts";
import { AgentBadge } from "./AgentBadge";
import { EmptyState } from "./States";

type Filter = "all" | "peer" | "refused";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "peer", label: "Peer only" },
  { id: "refused", label: "Refusals" },
];

const TYPE_LABEL: Record<A2AMessageType, string> = {
  task: "task",
  peer_request: "peer request",
  peer_response: "peer response",
  result: "result",
  error: "error",
  clarification: "clarification",
};

const TYPE_TONE: Record<A2AMessageType, string> = {
  task: "bg-agent-ceo/10 text-agent-ceo",
  peer_request: "bg-agent-tech/10 text-agent-tech",
  peer_response: "bg-ok/10 text-ok",
  result: "bg-paper text-muted",
  error: "bg-fail/10 text-fail",
  clarification: "bg-warn/10 text-warn",
};

// Delegation depth is shown as indentation so a peer chain reads as a staircase.
const INDENT = ["pl-0", "pl-4", "pl-8", "pl-12"];

function matches(item: FeedMessage, filter: Filter): boolean {
  if (filter === "refused") return item.refused;
  if (filter === "peer") return item.message.type === "peer_request" || item.message.type === "peer_response";
  return true;
}

const MessageRow = memo(function MessageRow({ item }: { item: FeedMessage }) {
  const { message, refused, refusalReason } = item;
  const [expanded, setExpanded] = useState(false);
  const tone = agentTone(message.sender);
  const indent = INDENT[Math.min(message.hop_count, INDENT.length - 1)];

  return (
    <li className={`relative animate-enter ${indent}`}>
      <div className={`rounded-md border bg-surface px-2.5 py-2 ${refused ? "border-fail/40" : "border-line"}`}>
        <div className="flex flex-wrap items-center gap-1.5">
          <span aria-hidden className={`size-2 rounded-full ${refused ? "bg-fail" : tone.dot}`} />
          <AgentBadge name={message.sender} />
          <ArrowRight aria-label="to" className="size-3 text-faint" />
          <AgentBadge name={message.recipient} />
          <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${TYPE_TONE[message.type]}`}>
            {TYPE_LABEL[message.type]}
          </span>
          <span className="ml-auto text-[11px] text-faint tabular-nums">
            hop {message.hop_count}
            <span className="mx-1 text-line">|</span>
            <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>
          </span>
        </div>

        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className={`mt-1 block w-full text-left text-xs text-ink/85 ${expanded ? "" : "line-clamp-2"}`}
        >
          {message.content}
        </button>

        {refused ? (
          <p className="mt-1.5 flex items-start gap-1 rounded bg-fail/5 px-1.5 py-1 text-xs text-fail">
            <Ban aria-hidden className="mt-0.5 size-3 shrink-0" />
            <span>Refused: {refusalReason ?? "no reason given"}</span>
          </p>
        ) : null}

        {message.chain.length > 1 ? (
          <p className="mt-1 text-[11px] text-faint">
            Chain: {message.chain.map(agentLabel).join(" > ")}
          </p>
        ) : null}
      </div>
    </li>
  );
});

interface A2APanelProps {
  turns: Turn[];
  streaming: boolean;
}

export const A2APanel = memo(function A2APanel({ turns, streaming }: A2APanelProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const listRef = useRef<HTMLDivElement>(null);

  const { groups, total, peerCount, refusedCount } = useMemo(() => {
    let totalCount = 0;
    let peers = 0;
    let refusals = 0;
    const grouped = turns.map((turn) => {
      for (const item of turn.run.messages) {
        totalCount += 1;
        if (item.message.type === "peer_request") peers += 1;
        if (item.refused) refusals += 1;
      }
      return { turn, items: turn.run.messages.filter((item) => matches(item, filter)) };
    });
    return { groups: grouped.filter((group) => group.items.length > 0), total: totalCount, peerCount: peers, refusedCount: refusals };
  }, [turns, filter]);

  // Follow new messages while a request is streaming, unless the user scrolled up.
  useEffect(() => {
    const element = listRef.current;
    if (!element || !streaming) return;
    const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 160;
    if (nearBottom) element.scrollTop = element.scrollHeight;
  }, [total, streaming]);

  return (
    <aside aria-label="Agent-to-agent activity" className="flex min-h-0 flex-1 flex-col bg-surface">
      <header className="border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <Network aria-hidden className="size-4 text-chrome" />
          <h2 className="text-sm font-semibold">A2A activity</h2>
          {streaming ? (
            <span className="ml-auto inline-flex items-center gap-1.5 text-xs text-agent-tech">
              <span aria-hidden className="size-1.5 animate-pulse-dot rounded-full bg-agent-tech" />
              Live
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-xs text-muted">
          {total} messages, {peerCount} peer {peerCount === 1 ? "request" : "requests"}, {refusedCount}{" "}
          {refusedCount === 1 ? "refusal" : "refusals"}
        </p>
        <div role="radiogroup" aria-label="Filter messages" className="mt-2 inline-flex rounded-md border border-line p-0.5">
          {FILTERS.map((option) => (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={filter === option.id}
              onClick={() => setFilter(option.id)}
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                filter === option.id ? "bg-chrome text-white" : "text-muted hover:text-ink"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>

      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {groups.length === 0 ? (
          <EmptyState icon={<Network className="size-7" />} title={total === 0 ? "No messages yet" : "Nothing matches this filter"}>
            {total === 0
              ? "Tasks from the CEO and requests between departments appear here as they happen."
              : "Switch the filter back to All to see every message."}
          </EmptyState>
        ) : (
          <div className="space-y-5">
            {groups.map(({ turn, items }) => (
              <section key={turn.id} aria-label={turn.question}>
                <h3 className="mb-2 line-clamp-1 text-xs font-medium text-muted" title={turn.question}>
                  {turn.question}
                </h3>
                <ol className="space-y-1.5">
                  {items.map((item) => (
                    <MessageRow key={item.message.id} item={item} />
                  ))}
                </ol>
              </section>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
});
