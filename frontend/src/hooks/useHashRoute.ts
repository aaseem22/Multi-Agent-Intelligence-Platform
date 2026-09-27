import { useCallback, useSyncExternalStore } from "react";

export type Route = { page: "chat"; conversationId: string | null } | { page: "agents" };

function parse(hash: string): Route {
  const path = hash.replace(/^#/, "");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "agents") return { page: "agents" };
  if (parts[0] === "chat" && parts[1]) return { page: "chat", conversationId: decodeURIComponent(parts[1]) };
  return { page: "chat", conversationId: null };
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

const getHash = () => window.location.hash;

export function chatHref(conversationId: string | null): string {
  return conversationId ? `#/chat/${encodeURIComponent(conversationId)}` : "#/chat";
}

export const AGENTS_HREF = "#/agents";

/** Tiny hash router: enough for three screens without pulling in a routing library. */
export function useHashRoute(): [Route, (href: string) => void] {
  const hash = useSyncExternalStore(subscribe, getHash);
  const navigate = useCallback((href: string) => {
    if (window.location.hash !== href) window.location.hash = href;
  }, []);
  return [parse(hash), navigate];
}
