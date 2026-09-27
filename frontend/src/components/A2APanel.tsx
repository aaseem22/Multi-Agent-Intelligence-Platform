import { memo, useEffect, useMemo, useRef, useState } from "react";
import { agentLabel, agentStroke } from "../lib/agents";
import { formatTime } from "../lib/format";
import type { FeedMessage, Turn } from "../lib/run";
import type { A2AMessageType } from "../types/contracts";
import { AgentName } from "./AgentName";
import { EmptyState } from "./States";

type Filter = "all" | "peer" | "refused";

const TYPE_LABEL: Record<A2AMessageType, string> = {
  task: "task",
  peer_request: "peer request",
  peer_response: "peer response",
  result: "result",
  error: "error",
  clarification: "clarification",
};

// Geometry of the delegation tree: each hop steps the node 18px to the right.
const STEP = 18;
const SPINE = 5;
const MAX_DEPTH = 4;
const nodeX = (depth: number) => SPINE + depth * STEP;

function matches(item: FeedMessage, filter: Filter): boolean {
  if (filter === "refused") return item.refused;
  if (filter === "peer") return item.message.type === "peer_request" || item.message.type === "peer_response";
  return true;
}

const MessageRow = memo(function MessageRow({ item }: { item: FeedMessage }) {
  const { message, refused, refusalReason } = item;
  const [expanded, setExpanded] = useState(false);
  const depth = Math.min(message.hop_count, MAX_DEPTH);
  const x = nodeX(depth);
  const guides = Array.from({ length: depth }, (_, level) => nodeX(level));

  return (
    <li className="relative animate-enter pt-1 pb-3" style={{ paddingLeft: x + 14 }}>
      {guides.map((left) => (
        <span key={left} aria-hidden className="absolute inset-y-0 w-px bg-rule-strong" style={{ left }} />
      ))}
      {depth === 0 ? <span aria-hidden className="absolute inset-y-0 w-px bg-rule-strong" style={{ left: SPINE }} /> : null}
      {depth > 0 ? (
        <span
          aria-hidden
          className="absolute top-0 h-[0.95rem] rounded-bl-[5px] border-b border-l border-rule-strong"
          style={{ left: nodeX(depth - 1), width: STEP }}
        />
      ) : null}
      {refused ? (
        <span
          aria-hidden
          className="absolute top-[0.3rem] -ml-[7px] bg-paper-deep text-sm leading-none text-refuse"
          style={{ left: x }}
        >
          ⊘
        </span>
      ) : (
        <span
          aria-hidden
          className={`absolute top-[0.6rem] size-[7px] -translate-x-[3px] ${agentStroke(message.sender)} ${
            message.type === "peer_response" ? "rounded-full" : ""
          }`}
          style={{ left: x }}
        />
      )}

      <div className="flex items-baseline gap-2 text-xs">
        <span className="min-w-0">
          <AgentName name={message.sender} />
          <span aria-label="to" className="px-1 text-pencil">
            →
          </span>
          <AgentName name={message.recipient} />
          <span className={`ml-2 italic ${refused ? "text-refuse" : "text-graphite"}`}>
            {refused ? "refused" : TYPE_LABEL[message.type]}
          </span>
        </span>
        <span className="ml-auto shrink-0 font-mono text-2xs whitespace-nowrap text-pencil">
          hop {message.hop_count}{" "}
          <time dateTime={message.created_at} className="ml-1">
            {formatTime(message.created_at)}
          </time>
        </span>
      </div>

      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className={`mt-0.5 block w-full text-left text-xs text-ink/85 hover:text-ink ${expanded ? "" : "line-clamp-2"}`}
      >
        {message.content}
      </button>

      {refused ? (
        <p className="mt-1 text-xs font-semibold text-refuse">Refused: {refusalReason ?? "no reason given"}</p>
      ) : null}

      {message.chain.length > 1 ? (
        <p className="mt-0.5 font-mono text-2xs text-pencil">
          <span className="sr-only">Chain: </span>
          {message.chain.map(agentLabel).join(" › ")}
        </p>
      ) : null}
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

  const { groups, total, peerCount, refusedCount, peerMessages } = useMemo(() => {
    let totalCount = 0;
    let peers = 0;
    let peerAll = 0;
    let refusals = 0;
    const grouped = turns.map((turn) => {
      for (const item of turn.run.messages) {
        totalCount += 1;
        if (item.message.type === "peer_request") peers += 1;
        if (item.message.type === "peer_request" || item.message.type === "peer_response") peerAll += 1;
        if (item.refused) refusals += 1;
      }
      return { turn, items: turn.run.messages.filter((item) => matches(item, filter)) };
    });
    return {
      groups: grouped.filter((group) => group.items.length > 0),
      total: totalCount,
      peerCount: peers,
      peerMessages: peerAll,
      refusedCount: refusals,
    };
  }, [turns, filter]);

  // Follow new messages while a request is streaming, unless the user scrolled up.
  useEffect(() => {
    const element = listRef.current;
    if (!element || !streaming) return;
    const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 160;
    if (nearBottom) element.scrollTop = element.scrollHeight;
  }, [total, streaming]);

  const filters: { id: Filter; label: string; count: number }[] = [
    { id: "all", label: "All", count: total },
    { id: "peer", label: "Between departments", count: peerMessages },
    { id: "refused", label: "Refused", count: refusedCount },
  ];

  return (
    <aside aria-label="Agent-to-agent activity" className="flex min-h-0 flex-1 flex-col bg-paper-deep">
      <header className="px-5 pt-4">
        <div className="flex items-baseline gap-3">
          <h2 className="text-base font-semibold">Messages between agents</h2>
          {streaming ? (
            <span className="ml-auto inline-flex items-baseline gap-1.5 text-xs text-ink">
              <span aria-hidden className="size-[6px] animate-breathe rounded-full bg-ink" />
              <span className="marked">live</span>
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 text-xs text-graphite">
          {total} {total === 1 ? "message" : "messages"}, {peerCount} peer{" "}
          {peerCount === 1 ? "request" : "requests"}, {refusedCount} {refusedCount === 1 ? "refusal" : "refusals"}
        </p>
        <div role="radiogroup" aria-label="Filter messages" className="mt-3 flex gap-4 border-b border-rule">
          {filters.map((option) => {
            const checked = filter === option.id;
            return (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={checked}
                onClick={() => setFilter(option.id)}
                className={`-mb-px border-b-2 pb-1.5 text-xs ${
                  checked ? "border-ink font-semibold text-ink" : "border-transparent text-graphite hover:text-ink"
                }`}
              >
                {option.label} <span className="font-mono text-2xs text-pencil">{option.count}</span>
              </button>
            );
          })}
        </div>
      </header>

      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-5 pt-3 pb-6">
        {groups.length === 0 ? (
          <EmptyState title={total === 0 ? "No messages yet" : "Nothing matches this filter"}>
            {total === 0
              ? "Tasks from the CEO and requests between departments are logged here as they happen. Indentation shows how many hops a request has travelled."
              : "Switch the filter back to All to see every message."}
          </EmptyState>
        ) : (
          <div className="space-y-6">
            {groups.map(({ turn, items }) => (
              <section key={turn.id} aria-label={turn.question}>
                <h3 className="mb-2 line-clamp-1 text-xs text-graphite italic" title={turn.question}>
                  {turn.question}
                </h3>
                <ol>
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
