// Request/response shapes for backend/app/api (section 13 of CLAUDE.md).

import type { A2AMessage, AgentCard } from "./contracts";

export interface ChatRequest {
  conversation_id?: string | null;
  message: string;
}

export type AgentsResponse = AgentCard[];

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationTurn {
  request_id: string;
  question: string;
  kind: "final" | "clarification" | "error" | "pending";
  answer: string | null;
  // for kind="final": { answer: FinalAnswer, results: AgentResult[] }
  payload: Record<string, unknown>;
  trace_url: string | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  turns: ConversationTurn[];
}

export type A2ALogResponse = A2AMessage[];

export interface HealthResponse {
  status: "ok" | "degraded";
  database: boolean;
  github_token: boolean;
  langfuse: boolean;
  agents: string[];
}
