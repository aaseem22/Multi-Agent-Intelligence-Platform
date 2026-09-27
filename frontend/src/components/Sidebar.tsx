import type { ReactNode } from "react";
import { formatRelative } from "../lib/format";
import { AGENTS_HREF, chatHref, observabilityHref, type Route } from "../hooks/useHashRoute";
import type { Resource } from "../hooks/useResource";
import type { ConversationSummary, HealthResponse } from "../types/api";
import { Spinner } from "./States";

interface SidebarProps {
  route: Route;
  history: Resource<ConversationSummary[]>;
  onRetryHistory: () => void;
  health: Resource<HealthResponse>;
  mode: "live" | "mock";
  onNavigate?: () => void;
}

function NavLink({ href, active, children, onNavigate }: {
  href: string;
  active: boolean;
  children: ReactNode;
  onNavigate?: () => void;
}) {
  return (
    <a
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`block py-1 text-base ${active ? "font-semibold text-ink" : "text-graphite hover:text-ink"}`}
    >
      <span className={active ? "marked" : ""}>{children}</span>
    </a>
  );
}

function HistoryList({ route, history, onRetryHistory, onNavigate }: Pick<SidebarProps, "route" | "history" | "onRetryHistory" | "onNavigate">) {
  const activeId = route.page === "chat" ? route.conversationId : null;

  if (history.status === "loading" && !history.data) {
    return (
      <p role="status" className="flex items-baseline gap-2 py-2 text-xs text-graphite italic">
        Loading conversations
        <Spinner />
      </p>
    );
  }
  if (history.status === "error" && !history.data) {
    return (
      <div role="alert" className="border-l-2 border-refuse py-1 pl-3 text-xs">
        <p className="text-graphite">Could not load conversations: {history.error}</p>
        <button type="button" onClick={onRetryHistory} className="link mt-1 font-semibold text-ink">
          Try again
        </button>
      </div>
    );
  }
  const items = history.data ?? [];
  if (items.length === 0) {
    return <p className="py-2 text-xs text-graphite italic">Past questions are listed here after you ask one.</p>;
  }
  return (
    <ol>
      {items.map((conversation) => {
        const active = conversation.id === activeId;
        return (
          <li key={conversation.id} className="border-t border-rule first:border-t-0">
            <a
              href={chatHref(conversation.id)}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={`group block py-2 ${active ? "text-ink" : "text-graphite hover:text-ink"}`}
            >
              <span className={`line-clamp-2 text-sm ${active ? "font-semibold" : ""}`}>
                <span className={active ? "marked" : ""}>{conversation.title || "Untitled conversation"}</span>
              </span>
              <time dateTime={conversation.updated_at} className="font-mono text-2xs text-pencil">
                {formatRelative(conversation.updated_at)}
              </time>
            </a>
          </li>
        );
      })}
    </ol>
  );
}

function HealthLine({ health, mode }: Pick<SidebarProps, "health" | "mode">) {
  if (mode === "mock") {
    return (
      <p className="text-xs text-graphite">
        <span aria-hidden className="mr-1.5 text-caution">◆</span>
        Mock mode: scripted runs, no backend
      </p>
    );
  }
  if (health.status === "loading") {
    return (
      <p className="flex items-baseline gap-2 text-xs text-graphite italic">
        Checking backend
        <Spinner />
      </p>
    );
  }
  if (health.status === "error") {
    return (
      <p className="text-xs text-graphite" title={health.error}>
        <span aria-hidden className="mr-1.5 text-refuse">●</span>
        Backend unreachable on :8000
      </p>
    );
  }
  const data = health.data;
  const missing = [
    data.database ? null : "database",
    data.github_token ? null : "GitHub token",
    data.langfuse ? null : "Langfuse",
  ].filter(Boolean);
  return (
    <p className="text-xs text-graphite">
      <span aria-hidden className={`mr-1.5 ${data.status === "ok" ? "text-done" : "text-caution"}`}>●</span>
      {data.status === "ok" ? "Backend healthy" : "Backend degraded"}
      {missing.length > 0 ? `: no ${missing.join(", ")}` : ""}
    </p>
  );
}

export function Sidebar({ route, history, onRetryHistory, health, mode, onNavigate }: SidebarProps) {
  return (
    <nav aria-label="Main" className="flex h-full flex-col border-r border-rule bg-paper px-5">
      <div className="pt-5 pr-14 pb-5 md:pr-0">
        <p className="text-lg leading-tight font-semibold tracking-tight text-ink">Orchestration console</p>
        <p className="mt-0.5 text-xs text-graphite italic">CEO, Finance, HR and Tech agents</p>
      </div>
      <div className="border-t border-rule-strong pt-2 pb-4">
        <NavLink href={chatHref(null)} active={route.page === "chat" && route.conversationId === null} onNavigate={onNavigate}>
          New question
        </NavLink>
        <NavLink href={AGENTS_HREF} active={route.page === "agents"} onNavigate={onNavigate}>
          Agents
        </NavLink>
        <NavLink href={observabilityHref()} active={false} onNavigate={onNavigate}>
          Observability
        </NavLink>
      </div>
      <h2 className="flex items-baseline gap-2 border-t border-rule-strong pt-3 pb-1 text-xs font-semibold text-graphite">
        Earlier questions
        {history.status === "loading" && history.data ? <Spinner className="text-pencil" /> : null}
      </h2>
      <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-3">
        <HistoryList route={route} history={history} onRetryHistory={onRetryHistory} onNavigate={onNavigate} />
      </div>
      <div className="border-t border-rule py-3">
        <HealthLine health={health} mode={mode} />
      </div>
    </nav>
  );
}
