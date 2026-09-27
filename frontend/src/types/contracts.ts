// Mirrors backend/app/core/contracts.py exactly. Fixed interface: do not edit in Phase 1.

export interface Skill {
  name: string;
  description: string;
  example_questions: string[];
}

export interface AgentCard {
  name: string;
  department: string;
  description: string;
  skills: Skill[];
  owned_data: string[];
  accepts_peer_requests: boolean;
}

export type EvidenceSourceType = "db" | "github" | "peer";

export interface Evidence {
  source_type: EvidenceSourceType;
  source_ref: string; // e.g. "expenses:id=42", "github:repos/o/r/pulls?state=open", "peer:hr:msg_id"
  summary: string;
  data: Record<string, unknown> | null;
}

export interface Subtask {
  id: string;
  assigned_to: string;
  instruction: string;
  depends_on: string[];
}

export type A2AMessageType =
  | "task"
  | "peer_request"
  | "peer_response"
  | "result"
  | "error"
  | "clarification";

export interface A2AMessage {
  id: string;
  request_id: string;
  trace_id: string | null;
  sender: string;
  recipient: string;
  type: A2AMessageType;
  content: string;
  // peer_request refusals carry { refused: true, reason: string }
  payload: Record<string, unknown>;
  hop_count: number;
  chain: string[];
  created_at: string; // ISO 8601
}

export type AgentStatus = "ok" | "partial" | "failed" | "needs_clarification";

export interface AgentResult {
  agent: string;
  subtask_id: string;
  status: AgentStatus;
  answer: string;
  evidence: Evidence[];
  peer_messages: string[];
  error: string | null;
}

export interface EvalResult {
  passed: boolean;
  stage: "self" | "independent" | "evidence";
  reasons: string[];
  score: number | null;
}

export interface Plan {
  subtasks: Subtask[];
  clarification: string | null;
  rationale: string;
}

export interface Claim {
  text: string;
  evidence_refs: string[]; // source_ref values of Evidence in the results
  agents: string[];
}

export interface FinalAnswer {
  answer: string;
  claims: Claim[];
  unanswered: string[];
}
