import { History, Plus, Users } from "lucide-react";
import type { ReactNode } from "react";
import { formatRelative } from "../lib/format";
import { AGENTS_HREF, chatHref, type Route } from "../hooks/useHashRoute";
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

function NavLink({ href, active, icon, children, onNavigate }: {
  href: string;
  active: boolean;
  icon: ReactNode;
  children: ReactNode;
  onNavigate?: () => void;
}) {
  return (
    <a
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm font-medium ${
        active ? "bg-chrome-soft text-white" : "text-chrome-text hover:bg-chrome-soft/60 hover:text-white"
      }`}
    >
      {icon}
      {children}
    </a>
  );
}

function HistoryList({ route, history, onRetryHistory, onNavigate }: Pick<SidebarProps, "route" | "history" | "onRetryHistory" | "onNavigate">) {
  const activeId = route.page === "chat" ? route.conversationId : null;

  if (history.status === "loading" && !history.data) {
    return (
      <p role="status" className="flex items-center gap-2 px-2.5 py-2 text-xs text-chrome-text">
        <Spinner className="size-3.5" />
        Loading conversations
      </p>
    );
  }
  if (history.status === "error" && !history.data) {
    return (
      <div role="alert" className="px-2.5 py-2 text-xs text-chrome-text">
        <p>Could not load conversations: {history.error}</p>
        <button type="button" onClick={onRetryHistory} className="mt-1 font-medium text-signal hover:underline">
          Try again
        </button>
      </div>
    );
  }
  const items = history.data ?? [];
  if (items.length === 0) {
    return <p className="px-2.5 py-2 text-xs text-chrome-text/80">Past questions appear here after you ask one.</p>;
  }
  return (
    <ul className="space-y-0.5">
      {items.map((conversation) => {
        const active = conversation.id === activeId;
        return (
          <li key={conversation.id}>
            <a
              href={chatHref(conversation.id)}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={`block rounded-md px-2.5 py-1.5 ${
                active ? "bg-chrome-soft text-white" : "text-chrome-text hover:bg-chrome-soft/60 hover:text-white"
              }`}
            >
              <span className="line-clamp-2 text-sm">{conversation.title || "Untitled conversation"}</span>
              <time dateTime={conversation.updated_at} className="text-[11px] text-chrome-text/70">
                {formatRelative(conversation.updated_at)}
              </time>
            </a>
          </li>
        );
      })}
    </ul>
  );
}

function HealthLine({ health, mode }: Pick<SidebarProps, "health" | "mode">) {
  if (mode === "mock") {
    return (
      <p className="flex items-center gap-2 text-xs text-chrome-text">
        <span aria-hidden className="size-2 rounded-full bg-signal" />
        Mock mode: scripted runs, no backend
      </p>
    );
  }
  if (health.status === "loading") {
    return (
      <p className="flex items-center gap-2 text-xs text-chrome-text">
        <Spinner className="size-3" />
        Checking backend
      </p>
    );
  }
  if (health.status === "error") {
    return (
      <p className="flex items-center gap-2 text-xs text-chrome-text" title={health.error}>
        <span aria-hidden className="size-2 rounded-full bg-fail" />
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
    <p className="flex items-start gap-2 text-xs text-chrome-text">
      <span aria-hidden className={`mt-1 size-2 shrink-0 rounded-full ${data.status === "ok" ? "bg-ok" : "bg-warn"}`} />
      <span>
        {data.status === "ok" ? "Backend healthy" : "Backend degraded"}
        {missing.length > 0 ? `: no ${missing.join(", ")}` : ""}
      </span>
    </p>
  );
}

export function Sidebar({ route, history, onRetryHistory, health, mode, onNavigate }: SidebarProps) {
  return (
    <nav aria-label="Main" className="flex h-full flex-col bg-chrome text-white">
      <div className="px-4 pt-4 pb-3">
        <p className="text-[15px] font-semibold tracking-tight">Orchestration console</p>
        <p className="text-xs text-chrome-text">CEO, Finance, HR and Tech agents</p>
      </div>
      <div className="space-y-0.5 px-2">
        <NavLink
          href={chatHref(null)}
          active={route.page === "chat" && route.conversationId === null}
          icon={<Plus aria-hidden className="size-4" />}
          onNavigate={onNavigate}
        >
          New question
        </NavLink>
        <NavLink href={AGENTS_HREF} active={route.page === "agents"} icon={<Users aria-hidden className="size-4" />} onNavigate={onNavigate}>
          Agents
        </NavLink>
      </div>
      <div className="mt-5 flex items-center gap-2 px-4 pb-1.5 text-xs font-medium text-chrome-text">
        <History aria-hidden className="size-3.5" />
        Conversations
        {history.status === "loading" && history.data ? <Spinner className="size-3" /> : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        <HistoryList route={route} history={history} onRetryHistory={onRetryHistory} onNavigate={onNavigate} />
      </div>
      <div className="border-t border-chrome-soft px-4 py-3">
        <HealthLine health={health} mode={mode} />
      </div>
    </nav>
  );
}
