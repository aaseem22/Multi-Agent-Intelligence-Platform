import {
  Activity,
  Bot,
  FlaskConical,
  MessageSquarePlus,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
  Waypoints,
  type LucideIcon,
} from "lucide-react";
import { formatRelative } from "../lib/format";
import { AGENTS_HREF, chatHref, evalsHref, observabilityHref, type Route } from "../hooks/useHashRoute";
import type { ThemeChoice } from "../hooks/usePreferences";
import type { Resource } from "../hooks/useResource";
import type { ConversationSummary, HealthResponse } from "../types/api";

interface SidebarProps {
  route: Route;
  history: Resource<ConversationSummary[]>;
  onRetryHistory: () => void;
  health: Resource<HealthResponse>;
  mode: "live" | "mock";
  theme: ThemeChoice;
  onThemeChange: (choice: ThemeChoice) => void;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  onNavigate?: () => void;
}

export function BrandMark({ size = "md" }: { size?: "sm" | "md" }) {
  const box = size === "sm" ? "size-7 rounded-[8px]" : "size-9 rounded-[10px]";
  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden bg-linear-to-br from-accent to-accent-strong text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_4px_12px_-4px_var(--color-glow)] dark:text-canvas ${box}`}
    >
      <Waypoints aria-hidden size={size === "sm" ? 15 : 18} strokeWidth={1.9} />
    </span>
  );
}

function NavLink({
  href,
  active,
  icon: Icon,
  label,
  collapsed,
  onNavigate,
}: {
  href: string;
  active: boolean;
  icon: LucideIcon;
  label: string;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  return (
    <a
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? label : undefined}
      title={collapsed ? label : undefined}
      className={`group relative flex h-9 items-center gap-2.5 rounded-block text-base transition-colors duration-150 ${
        collapsed ? "w-9 justify-center" : "px-2.5"
      } ${active ? "bg-surface font-medium text-ink shadow-card ring-1 ring-line" : "text-ink-2 hover:bg-surface/60 hover:text-ink"}`}
    >
      <Icon
        aria-hidden
        size={17}
        strokeWidth={1.75}
        className={active ? "text-accent" : "text-faint transition-colors group-hover:text-ink-2"}
      />
      {collapsed ? null : label}
    </a>
  );
}

function HistoryList({ route, history, onRetryHistory, onNavigate }: Pick<SidebarProps, "route" | "history" | "onRetryHistory" | "onNavigate">) {
  const activeId = route.page === "chat" ? route.conversationId : null;

  if (history.status === "loading" && !history.data) {
    return (
      <div role="status" aria-label="Loading conversations" className="space-y-2.5 px-2.5 py-2">
        {[80, 64, 72].map((w) => (
          <div key={w} className="skeleton h-3" style={{ width: `${w}%` }} />
        ))}
      </div>
    );
  }
  if (history.status === "error" && !history.data) {
    return (
      <div role="alert" className="px-2.5 py-2 text-xs">
        <p className="text-muted">Could not load conversations: {history.error}</p>
        <button type="button" onClick={onRetryHistory} className="link mt-1 font-medium">
          Try again
        </button>
      </div>
    );
  }
  const items = history.data ?? [];
  if (items.length === 0) {
    return <p className="px-2.5 py-2 text-xs text-muted">Your questions appear here after you ask one.</p>;
  }
  return (
    <ol className="space-y-0.5">
      {items.map((conversation) => {
        const active = conversation.id === activeId;
        return (
          <li key={conversation.id}>
            <a
              href={chatHref(conversation.id)}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={`block rounded-block px-2.5 py-2 transition-colors duration-150 ${
                active ? "bg-surface shadow-card ring-1 ring-line" : "hover:bg-surface/60"
              }`}
            >
              <span className={`line-clamp-2 text-sm leading-snug ${active ? "font-medium text-ink" : "text-ink-2"}`}>
                {conversation.title || "Untitled conversation"}
              </span>
              <time dateTime={conversation.updated_at} className="mt-0.5 block text-2xs text-faint">
                {formatRelative(conversation.updated_at)}
              </time>
            </a>
          </li>
        );
      })}
    </ol>
  );
}

function healthState({ health, mode }: Pick<SidebarProps, "health" | "mode">) {
  if (mode === "mock") return { dot: "bg-warn", title: "Mock mode", detail: "Scripted runs, no backend" };
  if (health.status === "error") return { dot: "bg-danger", title: "Backend unreachable", detail: health.error };
  if (health.status !== "ready") return { dot: "bg-faint", title: "Checking backend", detail: null };
  const data = health.data;
  const missing = [data.database ? null : "database", data.github_token ? null : "GitHub token", data.langfuse ? null : "Langfuse"].filter(Boolean);
  return {
    dot: data.status === "ok" ? "bg-ok" : "bg-warn",
    title: data.status === "ok" ? "All systems running" : "Backend degraded",
    detail: missing.length > 0 ? `No ${missing.join(", ")}` : `${data.agents.length} agents online`,
  };
}

function HealthLine({ health, mode, collapsed }: Pick<SidebarProps, "health" | "mode"> & { collapsed: boolean }) {
  const state = healthState({ health, mode });
  if (collapsed) {
    return (
      <span title={`${state.title}${state.detail ? `: ${state.detail}` : ""}`} className="flex size-9 items-center justify-center">
        <span aria-hidden className={`size-2 rounded-full ${state.dot}`} />
        <span className="sr-only">{state.title}</span>
      </span>
    );
  }
  return (
    <div className="flex items-center gap-2.5 rounded-block border border-line bg-surface px-3 py-2.5 shadow-card">
      <span aria-hidden className={`size-2 shrink-0 rounded-full ${state.dot}`} />
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">{state.title}</p>
        {state.detail ? (
          <p className="truncate text-2xs text-muted" title={state.detail}>
            {state.detail}
          </p>
        ) : null}
      </div>
    </div>
  );
}

const THEMES: { id: ThemeChoice; label: string; icon: LucideIcon }[] = [
  { id: "light", label: "Light", icon: Sun },
  { id: "dark", label: "Dark", icon: Moon },
  { id: "system", label: "System", icon: Monitor },
];

/** Three-way theme control. Collapsed, it becomes one button that cycles through the options. */
function ThemeSwitch({ theme, onThemeChange, collapsed }: { theme: ThemeChoice; onThemeChange: (c: ThemeChoice) => void; collapsed: boolean }) {
  if (collapsed) {
    const index = THEMES.findIndex((t) => t.id === theme);
    const current = THEMES[index];
    const next = THEMES[(index + 1) % THEMES.length];
    const Icon = current.icon;
    return (
      <button
        type="button"
        onClick={() => onThemeChange(next.id)}
        className="btn btn-ghost btn-icon"
        aria-label={`Theme: ${current.label}. Switch to ${next.label}`}
        title={`Theme: ${current.label}`}
      >
        <Icon aria-hidden size={16} strokeWidth={1.75} />
      </button>
    );
  }
  return (
    <div role="radiogroup" aria-label="Colour theme" className="flex gap-1 rounded-block bg-subtle p-1">
      {THEMES.map(({ id, label, icon: Icon }) => {
        const checked = theme === id;
        return (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={checked}
            onClick={() => onThemeChange(id)}
            className={`flex h-7 flex-1 items-center justify-center gap-1.5 rounded-[7px] text-xs transition-colors ${
              checked ? "bg-surface font-medium text-ink shadow-card" : "text-muted hover:text-ink"
            }`}
          >
            <Icon aria-hidden size={13} strokeWidth={1.9} />
            {label}
          </button>
        );
      })}
    </div>
  );
}

export function Sidebar({
  route,
  history,
  onRetryHistory,
  health,
  mode,
  theme,
  onThemeChange,
  collapsed = false,
  onToggleCollapsed,
  onNavigate,
}: SidebarProps) {
  const links: { href: string; icon: LucideIcon; label: string; active: boolean }[] = [
    { href: chatHref(null), icon: MessageSquarePlus, label: "New question", active: route.page === "chat" && route.conversationId === null },
    { href: AGENTS_HREF, icon: Bot, label: "Agents", active: route.page === "agents" },
    { href: evalsHref(), icon: FlaskConical, label: "Evals", active: route.page === "evals" },
    { href: observabilityHref(), icon: Activity, label: "Observability", active: route.page === "observability" },
  ];

  return (
    <nav aria-label="Main" className={`frost flex h-full flex-col ${collapsed ? "items-center px-2" : "px-3"}`}>
      <div className={`flex items-center pt-5 pb-6 ${collapsed ? "flex-col gap-3" : "justify-between gap-2 px-1"}`}>
        <a href={chatHref(null)} onClick={onNavigate} className="flex min-w-0 items-center gap-2.5" aria-label="Orchestrator home">
          <BrandMark />
          {collapsed ? null : (
            <span className="min-w-0">
              <span className="block text-base leading-tight font-semibold tracking-tight text-ink">Orchestrator</span>
              <span className="block text-2xs text-muted">Multi-agent console</span>
            </span>
          )}
        </a>
        {onToggleCollapsed ? (
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="btn btn-ghost btn-icon size-8! text-faint hover:text-ink"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={`${collapsed ? "Expand" : "Collapse"} sidebar (Ctrl or Cmd + B)`}
          >
            {collapsed ? (
              <PanelLeftOpen aria-hidden size={16} strokeWidth={1.75} />
            ) : (
              <PanelLeftClose aria-hidden size={16} strokeWidth={1.75} />
            )}
          </button>
        ) : null}
      </div>

      <div className={`space-y-1 ${collapsed ? "flex flex-col items-center" : ""}`}>
        {links.map((link) => (
          <NavLink key={link.label} {...link} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </div>

      {collapsed ? (
        <div className="flex-1" />
      ) : (
        <>
          <h2 className="mt-7 mb-1.5 px-2.5 text-2xs font-medium text-faint">Recent questions</h2>
          <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-3">
            <HistoryList route={route} history={history} onRetryHistory={onRetryHistory} onNavigate={onNavigate} />
          </div>
        </>
      )}

      <div className={`space-y-2.5 pt-2 pb-4 ${collapsed ? "flex flex-col items-center" : ""}`}>
        <ThemeSwitch theme={theme} onThemeChange={onThemeChange} collapsed={collapsed} />
        <HealthLine health={health} mode={mode} collapsed={collapsed} />
      </div>
    </nav>
  );
}
