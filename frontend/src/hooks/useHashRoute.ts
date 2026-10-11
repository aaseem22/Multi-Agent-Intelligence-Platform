import { useCallback, useSyncExternalStore } from "react";

export type Route =
  | { page: "chat"; conversationId: string | null }
  | { page: "agents" }
  | { page: "observability"; traceId: string | null }
  | { page: "evals"; view: EvalsView };

export type EvalsView =
  | { kind: "overview" }
  | { kind: "runs" }
  | { kind: "run"; runId: string }
  | { kind: "trial"; runId: string; trialId: string }
  | { kind: "calibration" }
  | { kind: "self-eval" }
  | { kind: "dataset" };

function parseEvals(parts: string[]): EvalsView {
  const [section, id, sub, trialId] = parts.map((part) => decodeURIComponent(part));
  if (section === "runs" && id && sub === "trials" && trialId) return { kind: "trial", runId: id, trialId };
  if (section === "runs" && id) return { kind: "run", runId: id };
  if (section === "runs") return { kind: "runs" };
  if (section === "calibration") return { kind: "calibration" };
  if (section === "self-eval") return { kind: "self-eval" };
  if (section === "dataset") return { kind: "dataset" };
  return { kind: "overview" };
}

function parse(hash: string): Route {
  const path = hash.replace(/^#/, "");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "agents") return { page: "agents" };
  if (parts[0] === "observability") {
    return { page: "observability", traceId: parts[1] ? decodeURIComponent(parts[1]) : null };
  }
  if (parts[0] === "evals") return { page: "evals", view: parseEvals(parts.slice(1)) };
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

export function observabilityHref(traceId: string | null = null): string {
  return traceId ? `#/observability/${encodeURIComponent(traceId)}` : "#/observability";
}

export function evalsHref(view: EvalsView = { kind: "overview" }): string {
  const enc = encodeURIComponent;
  switch (view.kind) {
    case "overview":
      return "#/evals";
    case "run":
      return `#/evals/runs/${enc(view.runId)}`;
    case "trial":
      return `#/evals/runs/${enc(view.runId)}/trials/${enc(view.trialId)}`;
    default:
      return `#/evals/${view.kind}`;
  }
}

/** Tiny hash router: enough for four screens without pulling in a routing library. */
export function useHashRoute(): [Route, (href: string) => void] {
  const hash = useSyncExternalStore(subscribe, getHash);
  const navigate = useCallback((href: string) => {
    if (window.location.hash !== href) window.location.hash = href;
  }, []);
  return [parse(hash), navigate];
}
