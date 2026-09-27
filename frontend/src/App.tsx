import { lazy, Suspense, useCallback, useState } from "react";
import { backend } from "./api/backend";
import { Sidebar } from "./components/Sidebar";
import { chatHref, useHashRoute } from "./hooks/useHashRoute";
import { useResource } from "./hooks/useResource";
import { AgentsPage } from "./pages/AgentsPage";
import { ChatPage } from "./pages/ChatPage";

// The observability dashboard has its own theme, fonts and charts; load it only when opened.
const ObservabilityPage = lazy(() => import("./observability/ObservabilityPage"));

const fetchConversations = (signal: AbortSignal) => backend.getConversations(signal);
const fetchHealth = (signal: AbortSignal) => backend.getHealth(signal);

export default function App() {
  const [route, navigate] = useHashRoute();
  const [history, reloadHistory] = useResource(fetchConversations, "conversations");
  const [health] = useResource(fetchHealth, "health");
  const [drawerOpen, setDrawerOpen] = useState(false);

  const onConversationCreated = useCallback((id: string) => navigate(chatHref(id)), [navigate]);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  const sidebarProps = { route, history, onRetryHistory: reloadHistory, health, mode: backend.mode };

  if (route.page === "observability") {
    return (
      <Suspense fallback={<div className="h-full bg-[#05080e]" aria-busy="true" />}>
        <ObservabilityPage traceId={route.traceId} navigate={navigate} />
      </Suspense>
    );
  }

  return (
    <div className="flex h-full flex-col md:flex-row">
      <div className="hidden w-60 shrink-0 md:block">
        <Sidebar {...sidebarProps} />
      </div>

      <header className="flex items-baseline justify-between gap-3 border-b border-rule-strong bg-paper px-4 py-2.5 md:hidden">
        <span className="text-base font-semibold tracking-tight">Orchestration console</span>
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation"
          className="link text-sm text-ink"
        >
          Menu
        </button>
      </header>

      {drawerOpen ? (
        <div className="fixed inset-0 z-20 flex md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="relative w-72 max-w-[85vw] animate-enter">
            <Sidebar {...sidebarProps} onNavigate={closeDrawer} />
            <button
              type="button"
              onClick={closeDrawer}
              aria-label="Close navigation"
              className="link absolute top-5 right-4 text-sm text-ink"
            >
              Close
            </button>
          </div>
          <button type="button" aria-label="Close navigation" className="flex-1 bg-ink/30" onClick={closeDrawer} />
        </div>
      ) : null}

      <main className="min-h-0 min-w-0 flex-1">
        {route.page === "agents" ? (
          <AgentsPage />
        ) : (
          <ChatPage
            conversationId={route.conversationId}
            onConversationCreated={onConversationCreated}
            onRunSettled={reloadHistory}
          />
        )}
      </main>
    </div>
  );
}
