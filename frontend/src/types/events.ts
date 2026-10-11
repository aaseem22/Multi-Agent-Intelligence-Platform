// Mirrors backend/app/core/events.py exactly. Fixed interface: do not edit in Phase 1.
// SSE wire format from POST /api/chat:  "event: <type>\ndata: <JSON of the event>\n\n"

import type { JudgeVerdict } from "./evals";
import type {
  A2AMessage,
  AgentResult,
  EvalResult,
  FinalAnswer,
  Subtask,
} from "./contracts";

export type AgentMode = "task" | "peer";

interface BaseEvent {
  request_id: string;
  conversation_id: string;
  timestamp: string; // ISO 8601
}

export interface PlanEvent extends BaseEvent {
  type: "plan";
  subtasks: Subtask[];
  rationale: string;
}

export interface AgentStartedEvent extends BaseEvent {
  type: "agent_started";
  agent: string;
  subtask_id: string;
  mode: AgentMode;
  instruction: string;
}

export interface ToolCallEvent extends BaseEvent {
  type: "tool_call";
  agent: string;
  subtask_id: string;
  tool: string;
  args: Record<string, unknown>;
}

// Carries every A2A message: CEO task/result messages, peer requests/responses and refusals.
export interface PeerMessageEvent extends BaseEvent {
  type: "peer_message";
  message: A2AMessage;
  refused: boolean;
  refusal_reason: string | null;
}

export interface AgentResultEvent extends BaseEvent {
  type: "agent_result";
  mode: AgentMode;
  result: AgentResult;
}

export interface EvalResultEvent extends BaseEvent {
  type: "eval_result";
  agent: string;
  subtask_id: string;
  result: EvalResult;
  attempt: number; // 2+ when the agent was re-run by the recovery router
  judge: JudgeVerdict | null; // per-dimension detail for stage="independent"
}

// The recovery router acted on a failed evaluation.
export interface RecoveryEvent extends BaseEvent {
  type: "recovery";
  agent: string;
  subtask_id: string;
  action: "retry" | "replan" | "clarify" | "give_up";
  attempt: number;
  reasons: string[];
  feedback: string;
}

export interface FinalEvent extends BaseEvent {
  type: "final";
  answer: FinalAnswer;
  results: AgentResult[];
  trace_url: string | null;
}

export interface ClarificationEvent extends BaseEvent {
  type: "clarification";
  question: string;
}

export interface ErrorEvent extends BaseEvent {
  type: "error";
  message: string;
  agent: string | null;
}

export type StreamEvent =
  | PlanEvent
  | AgentStartedEvent
  | ToolCallEvent
  | PeerMessageEvent
  | AgentResultEvent
  | EvalResultEvent
  | RecoveryEvent
  | FinalEvent
  | ClarificationEvent
  | ErrorEvent;

export type StreamEventType = StreamEvent["type"];
