import type {
  A2ALogResponse,
  AgentsResponse,
  ChatRequest,
  ConversationDetail,
  ConversationSummary,
  HealthResponse,
} from "../types/api";
import type { StreamEvent } from "../types/events";

/** The surface both the live HTTP client and the mock implement. */
export interface Backend {
  mode: "live" | "mock";
  streamChat(request: ChatRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent>;
  getAgents(signal?: AbortSignal): Promise<AgentsResponse>;
  getConversations(signal?: AbortSignal): Promise<ConversationSummary[]>;
  getConversation(id: string, signal?: AbortSignal): Promise<ConversationDetail>;
  getConversationA2A(id: string, signal?: AbortSignal): Promise<A2ALogResponse>;
  getHealth(signal?: AbortSignal): Promise<HealthResponse>;
}
