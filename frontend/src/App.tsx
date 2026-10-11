import { Menu, X } from "lucide-react";
import { lazy, Suspense, useCallback, useState } from "react";
import { backend } from "./api/backend";
import { BrandMark, Sidebar } from "./components/Sidebar";
import { LoadingState } from "./components/States";
import { chatHref, useHashRoute } from "./hooks/useHashRoute";
import { useSidebarCollapsed, useTheme } from "./hooks/usePreferences";
import { useResource } from "./hooks/useResource";
import { AgentsPage } from "./pages/AgentsPage";
import { ChatPage } from "./pages/ChatPage";

// The observability dashboard carries its own charts; load it only when opened.
const ObservabilityPage = lazy(() => import("./observability/ObservabilityPage"));

const fetchConversations = (signal: AbortSignal) => backend.getConversations(signal);
const fetchHealth = (signal: AbortSignal) => backend.getHealth(signal);

export default function App() {
  const [route, navigate] = useHashRoute();
  const [history, reloadHistory] = useResource(fetchConversations, "conversations");
  const [health] = useResource(fetchHealth, "health");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [collapsed, toggleCollapsed] = useSidebarCollapsed();
  const { choice: theme, setChoice: setTheme } = useTheme();

  const onConversationCreated = useCallback((id: string) => navigate(chatHref(id)), [navigate]);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  const sidebarProps = {
    route,
    history,
    onRetryHistory: reloadHistory,
    health,
    mode: backend.mode,
    theme,
    onThemeChange: setTheme,
  };

  let page;
  if (route.page === "agents") page = <AgentsPage />;
  else if (route.page === "observability")
    page = (
      <Suspense
        fallback={
          <div className="p-10">
            <LoadingState label="Loading observability" lines={4} />
          </div>
        }
      >
        <ObservabilityPage traceId={route.traceId} navigate={navigate} />
      </Suspense>
    );
  else
    page = (
      <ChatPage conversationId={route.conversationId} onConversationCreated={onConversationCreated} onRunSettled={reloadHistory} />
    );

  return (
    <div className="grain relative flex h-full flex-col md:flex-row">
      <div aria-hidden className="ambient">
        <div className="dot-grid" />
      </div>

      <div
        className={`relative z-10 hidden shrink-0 border-r border-line transition-[width] duration-300 ease-out-soft md:block ${
          collapsed ? "w-17" : "w-64"
        }`}
      >
        <Sidebar {...sidebarProps} collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
      </div>

      <header className="frost relative z-10 flex items-center justify-between gap-3 border-b border-line px-4 py-2.5 md:hidden">
        <a href={chatHref(null)} className="flex items-center gap-2">
          <BrandMark size="sm" />
          <span className="text-base font-semibold tracking-tight">Orchestrator</span>
        </a>
        <button type="button" onClick={() => setDrawerOpen(true)} aria-label="Open navigation" className="btn btn-ghost btn-icon">
          <Menu aria-hidden size={18} strokeWidth={1.75} />
        </button>
      </header>

      {drawerOpen ? (
        <div className="fixed inset-0 z-30 flex md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="relative w-72 max-w-[85vw] animate-slide-in border-r border-line bg-canvas">
            <Sidebar {...sidebarProps} onNavigate={closeDrawer} />
            <button
              type="button"
              onClick={closeDrawer}
              aria-label="Close navigation"
              className="btn btn-ghost btn-icon absolute top-5 right-3"
            >
              <X aria-hidden size={18} strokeWidth={1.75} />
            </button>
          </div>
          <button type="button" aria-label="Close navigation" className="flex-1 animate-fade bg-ink/25" onClick={closeDrawer} />
        </div>
      ) : null}

      <main className="relative z-10 min-h-0 min-w-0 flex-1">{page}</main>
    </div>
  );
}
