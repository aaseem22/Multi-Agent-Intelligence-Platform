import { ArrowRight, Ban, MessagesSquare, PanelRightClose } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { agentLabel } from "../lib/agents";
import { formatTime } from "../lib/format";
import type { FeedMessage, Turn } from "../lib/run";
import type { A2AMessageType } from "../types/contracts";
import { AgentAvatar, AgentName } from "./AgentName";
import { RichText } from "./RichText";
import { EmptyState } from "./States";

type Filter = "all" | "peer" | "refused";

const TYPE_LABEL: Record<A2AMessageType, string> = {
  task: "Task",
  peer_request: "Peer request",
  peer_response: "Peer response",
  result: "Result",
  error: "Error",
  clarification: "Clarification",
};

const TYPE_TONE: Record<A2AMessageType, string> = {
  task: "bg-subtle text-ink-2",
  peer_request: "bg-accent-soft text-accent-strong",
  peer_response: "bg-accent-soft text-accent-strong",
  result: "bg-ok-soft text-ok",
  error: "bg-danger-soft text-danger",
  clarification: "bg-warn-soft text-warn",
};

// Each hop indents the message so delegation chains read as a tree.
const INDENT = 18;
const MAX_DEPTH = 3;

function matches(item: FeedMessage, filter: Filter): boolean {
  if (filter === "refused") return item.refused;
  if (filter === "peer") return item.message.type === "peer_request" || item.message.type === "peer_response";
  return true;
}

const MessageRow = memo(function MessageRow({ item }: { item: FeedMessage }) {
  const { message, refused, refusalReason } = item;
  const [expanded, setExpanded] = useState(false);
  const depth = Math.min(message.hop_count, MAX_DEPTH);

  return (
    <li className="relative pb-4 animate-enter" style={{ paddingLeft: depth * INDENT }}>
      <div
        className={`rounded-block border bg-surface p-3 shadow-card transition-colors ${
          refused ? "border-danger/30" : "border-line"
        }`}
      >
        <div className="flex items-center gap-2">
          <AgentAvatar name={message.sender} size="sm" />
          <span className="flex min-w-0 items-center gap-1 text-sm">
            <AgentName name={message.sender} />
            <ArrowRight aria-label="to" size={12} strokeWidth={2} className="shrink-0 text-faint" />
            <AgentName name={message.recipient} />
          </span>
          <time dateTime={message.created_at} className="ml-auto shrink-0 font-mono text-2xs text-faint">
            {formatTime(message.created_at)}
          </time>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {refused ? (
            <span className="chip bg-danger-soft text-danger">
              <Ban aria-hidden size={11} strokeWidth={2} />
              Refused
            </span>
          ) : (
            <span className={`chip ${TYPE_TONE[message.type]}`}>{TYPE_LABEL[message.type]}</span>
          )}
          <span className="mono-tag">hop {message.hop_count}</span>
          {message.chain.length > 1 ? (
            <span className="truncate font-mono text-2xs text-faint">
              <span className="sr-only">Chain: </span>
              {message.chain.map(agentLabel).join(" › ")}
            </span>
          ) : null}
        </div>

        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className={`mt-2 block w-full text-left text-sm leading-relaxed text-ink-2 transition-colors hover:text-ink ${
            expanded ? "" : "line-clamp-3"
          }`}
        >
          <RichText text={message.content} />
        </button>

        {refused ? (
          <p className="mt-2 rounded-md bg-danger-soft px-2.5 py-1.5 text-xs font-medium text-danger">
            {refusalReason ?? "No reason given"}
          </p>
        ) : null}
      </div>
    </li>
  );
});

interface A2APanelProps {
  turns: Turn[];
  streaming: boolean;
  /** Shown on wide screens, where the panel can be closed. */
  onClose?: () => void;
}

export const A2APanel = memo(function A2APanel({ turns, streaming, onClose }: A2APanelProps) {
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
    { id: "peer", label: "Peer", count: peerMessages },
    { id: "refused", label: "Refused", count: refusedCount },
  ];

  const stats = [
    { label: "Messages", value: total },
    { label: "Peer requests", value: peerCount },
    { label: "Refusals", value: refusedCount, alert: refusedCount > 0 },
  ];

  return (
    <aside aria-label="Agent-to-agent activity" className="frost flex min-h-0 flex-1 flex-col">
      <header className="border-b border-line px-5 pt-5 pb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold text-ink">Agent messages</h2>
          {streaming ? (
            <span className="chip ml-auto bg-accent-soft text-accent-strong">
              <span aria-hidden className="live-dot size-1.5!" />
              Live
            </span>
          ) : null}
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              className={`btn btn-ghost btn-icon hidden size-8! text-faint hover:text-ink lg:inline-flex ${streaming ? "" : "ml-auto"}`}
              aria-label="Hide agent messages"
              title="Hide agent messages"
            >
              <PanelRightClose aria-hidden size={16} strokeWidth={1.75} />
            </button>
          ) : null}
        </div>
        <dl className="mt-3 grid grid-cols-3 gap-2">
          {stats.map((stat) => (
            <div key={stat.label} className="rounded-block bg-subtle px-2.5 py-2">
              <dt className="text-2xs text-muted">{stat.label}</dt>
              <dd className={`mt-0.5 text-lg font-semibold tabular-nums ${stat.alert ? "text-danger" : "text-ink"}`}>{stat.value}</dd>
            </div>
          ))}
        </dl>
        <div role="radiogroup" aria-label="Filter messages" className="mt-3 flex gap-1 rounded-block bg-subtle p-1">
          {filters.map((option) => {
            const checked = filter === option.id;
            return (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={checked}
                onClick={() => setFilter(option.id)}
                className={`flex h-7 flex-1 items-center justify-center gap-1.5 rounded-[7px] text-xs transition-colors ${
                  checked ? "bg-surface font-medium text-ink shadow-card" : "text-muted hover:text-ink"
                }`}
              >
                {option.label}
                <span className="font-mono text-2xs text-faint">{option.count}</span>
              </button>
            );
          })}
        </div>
      </header>

      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 pb-6">
        {groups.length === 0 ? (
          <EmptyState
            title={total === 0 ? "No messages yet" : "Nothing matches this filter"}
            icon={<MessagesSquare size={20} strokeWidth={1.75} />}
          >
            {total === 0
              ? "Tasks from the CEO and requests between departments appear here as they happen. Indented messages travelled further hops."
              : "Switch the filter back to All to see every message."}
          </EmptyState>
        ) : (
          <div className="space-y-6">
            {groups.map(({ turn, items }) => (
              <section key={turn.id} aria-label={turn.question}>
                <h3 className="mb-3 line-clamp-1 px-1 text-xs font-medium text-muted" title={turn.question}>
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
