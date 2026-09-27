import { Menu, X } from "lucide-react";
import { useCallback, useState } from "react";
import { backend } from "./api/backend";
import { Sidebar } from "./components/Sidebar";
import { chatHref, useHashRoute } from "./hooks/useHashRoute";
import { useResource } from "./hooks/useResource";
import { AgentsPage } from "./pages/AgentsPage";
import { ChatPage } from "./pages/ChatPage";

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

  return (
    <div className="flex h-full flex-col md:flex-row">
      <div className="hidden w-64 shrink-0 md:block">
        <Sidebar {...sidebarProps} />
      </div>

      <header className="flex items-center gap-2 bg-chrome px-3 py-2 text-white md:hidden">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation"
          className="rounded-md p-1.5 hover:bg-chrome-soft"
        >
          <Menu aria-hidden className="size-5" />
        </button>
        <span className="text-sm font-semibold">Orchestration console</span>
      </header>

      {drawerOpen ? (
        <div className="fixed inset-0 z-20 flex md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="relative w-72 max-w-[85vw]">
            <Sidebar {...sidebarProps} onNavigate={closeDrawer} />
            <button
              type="button"
              onClick={closeDrawer}
              aria-label="Close navigation"
              className="absolute top-3 right-3 rounded-md p-1 text-chrome-text hover:text-white"
            >
              <X aria-hidden className="size-4" />
            </button>
          </div>
          <button type="button" aria-label="Close navigation" className="flex-1 bg-ink/40" onClick={closeDrawer} />
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
