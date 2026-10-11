// Real backend client for the endpoints in CLAUDE.md section 13.

import type {
  A2ALogResponse,
  AgentsResponse,
  ChatRequest,
  ConversationDetail,
  ConversationSummary,
  HealthResponse,
} from "../types/api";
import type { StreamEvent } from "../types/events";
import { readSseMessages, toStreamEvent } from "./sse";
import type { Backend } from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function describeFailure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // fall through to the status text
  }
  return `${response.status} ${response.statusText || "request failed"}`;
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" }, signal });
  if (!response.ok) throw new ApiError(response.status, await describeFailure(response));
  return (await response.json()) as T;
}

async function* streamChat(
  request: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) throw new ApiError(response.status, await describeFailure(response));
  if (!response.body) throw new ApiError(response.status, "The server returned an empty stream.");

  for await (const message of readSseMessages(response.body, signal)) {
    const event = toStreamEvent(message);
    if (event) yield event;
  }
}

async function cancelChat(requestId: string): Promise<void> {
  const response = await fetch(`/api/chat/${encodeURIComponent(requestId)}/cancel`, { method: "POST" });
  // 404 means the request already finished, which is fine for a stop button.
  if (!response.ok && response.status !== 404) throw new ApiError(response.status, await describeFailure(response));
}

export const httpBackend: Backend = {
  mode: "live",
  streamChat,
  cancelChat,
  getAgents: (signal) => getJson<AgentsResponse>("/api/agents", signal),
  getConversations: (signal) => getJson<ConversationSummary[]>("/api/conversations", signal),
  getConversation: (id, signal) =>
    getJson<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}`, signal),
  getConversationA2A: (id, signal) =>
    getJson<A2ALogResponse>(`/api/conversations/${encodeURIComponent(id)}/a2a`, signal),
  getHealth: (signal) => getJson<HealthResponse>("/api/health", signal),
};
