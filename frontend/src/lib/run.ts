// Folds the SSE event stream of one stakeholder request into view state.

import type { A2AMessage, AgentResult, AgentStatus, EvalResult, FinalAnswer, Subtask } from "../types/contracts";
import type { ConversationTurn } from "../types/api";
import type { JudgeVerdict } from "../types/evals";
import type { AgentMode, RecoveryEvent, StreamEvent } from "../types/events";

export type RunPhase = "planning" | "running" | "synthesising" | "done" | "clarification" | "error" | "cancelled";

export type AgentRunState = "queued" | "running" | AgentStatus;

export interface ToolCallRecord {
  tool: string;
  args: Record<string, unknown>;
  timestamp: string;
}

/** One review of an agent's result: the stage verdict, which attempt it judged, and the judge's detail. */
export interface EvalCheck {
  result: EvalResult;
  attempt: number;
  judge: JudgeVerdict | null;
}

/** What the recovery router did after a failed review. */
export interface RecoveryRecord {
  action: RecoveryEvent["action"];
  attempt: number;
  reasons: string[];
  feedback: string;
}

export interface AgentRun {
  key: string;
  agent: string;
  subtaskId: string;
  mode: AgentMode;
  instruction: string;
  state: AgentRunState;
  tools: ToolCallRecord[];
  evals: EvalCheck[];
  recoveries: RecoveryRecord[];
  result: AgentResult | null;
}

export interface FeedMessage {
  message: A2AMessage;
  refused: boolean;
  refusalReason: string | null;
}

export interface FinalOutcome {
  answer: FinalAnswer;
  results: AgentResult[];
}

export interface RunState {
  requestId: string | null;
  conversationId: string | null;
  phase: RunPhase;
  plan: { subtasks: Subtask[]; rationale: string } | null;
  runs: AgentRun[];
  messages: FeedMessage[];
  final: FinalOutcome | null;
  clarification: string | null;
  error: { message: string; agent: string | null } | null;
  traceUrl: string | null;
}

export interface Turn {
  id: string;
  question: string;
  createdAt: string;
  live: boolean;
  run: RunState;
}

export function emptyRun(): RunState {
  return {
    requestId: null,
    conversationId: null,
    phase: "planning",
    plan: null,
    runs: [],
    messages: [],
    final: null,
    clarification: null,
    error: null,
    traceUrl: null,
  };
}

function runKey(agent: string, subtaskId: string, mode: AgentMode): string {
  return `${mode}:${agent}:${subtaskId}`;
}

function upsertRun(runs: AgentRun[], key: string, patch: (run: AgentRun | undefined) => AgentRun): AgentRun[] {
  const index = runs.findIndex((run) => run.key === key);
  if (index === -1) return [...runs, patch(undefined)];
  const next = runs.slice();
  next[index] = patch(runs[index]);
  return next;
}

function blankRun(agent: string, subtaskId: string, mode: AgentMode, instruction: string): AgentRun {
  return {
    key: runKey(agent, subtaskId, mode),
    agent,
    subtaskId,
    mode,
    instruction,
    state: "queued",
    tools: [],
    evals: [],
    recoveries: [],
    result: null,
  };
}

/** Finds the run a tool call or eval belongs to: prefer a running peer run, then the task run. */
function findActiveKey(runs: AgentRun[], agent: string, subtaskId: string): string {
  const peer = runKey(agent, subtaskId, "peer");
  const peerRun = runs.find((run) => run.key === peer);
  if (peerRun && peerRun.state === "running") return peer;
  return runKey(agent, subtaskId, "task");
}

function allTasksSettled(runs: AgentRun[]): boolean {
  const tasks = runs.filter((run) => run.mode === "task");
  return tasks.length > 0 && tasks.every((run) => run.result !== null);
}

export function reduceRun(state: RunState, event: StreamEvent): RunState {
  const base: RunState = {
    ...state,
    requestId: state.requestId ?? event.request_id,
    conversationId: state.conversationId ?? event.conversation_id,
  };

  switch (event.type) {
    case "plan": {
      let runs = base.runs;
      for (const subtask of event.subtasks) {
        const key = runKey(subtask.assigned_to, subtask.id, "task");
        runs = upsertRun(runs, key, (run) => run ?? blankRun(subtask.assigned_to, subtask.id, "task", subtask.instruction));
      }
      return { ...base, phase: "running", plan: { subtasks: event.subtasks, rationale: event.rationale }, runs };
    }
    case "agent_started": {
      const key = runKey(event.agent, event.subtask_id, event.mode);
      const runs = upsertRun(base.runs, key, (run) => ({
        ...(run ?? blankRun(event.agent, event.subtask_id, event.mode, event.instruction)),
        instruction: event.instruction || run?.instruction || "",
        state: "running",
      }));
      // A self-evaluation retry can restart an agent after every task had settled.
      const phase = base.phase === "planning" || base.phase === "synthesising" ? "running" : base.phase;
      return { ...base, phase, runs };
    }
    case "tool_call": {
      const key = findActiveKey(base.runs, event.agent, event.subtask_id);
      const record: ToolCallRecord = { tool: event.tool, args: event.args, timestamp: event.timestamp };
      const runs = upsertRun(base.runs, key, (run) => {
        const current = run ?? { ...blankRun(event.agent, event.subtask_id, "task", ""), state: "running" as const };
        return { ...current, tools: [...current.tools, record] };
      });
      return { ...base, runs };
    }
    case "peer_message":
      return {
        ...base,
        messages: [
          ...base.messages,
          { message: event.message, refused: event.refused, refusalReason: event.refusal_reason },
        ],
      };
    case "agent_result": {
      const { result } = event;
      const key = runKey(result.agent, result.subtask_id, event.mode);
      const runs = upsertRun(base.runs, key, (run) => ({
        ...(run ?? blankRun(result.agent, result.subtask_id, event.mode, "")),
        state: result.status,
        result,
      }));
      const phase = base.phase === "running" && allTasksSettled(runs) ? "synthesising" : base.phase;
      return { ...base, runs, phase };
    }
    case "recovery": {
      // The retry itself arrives as a fresh agent_started for the same subtask.
      const key = runKey(event.agent, event.subtask_id, "task");
      const record: RecoveryRecord = { action: event.action, attempt: event.attempt, reasons: event.reasons, feedback: event.feedback };
      const runs = upsertRun(base.runs, key, (run) => {
        const current = run ?? blankRun(event.agent, event.subtask_id, "task", "");
        return { ...current, recoveries: [...current.recoveries, record] };
      });
      return { ...base, runs };
    }
    case "eval_result": {
      const key = runKey(event.agent, event.subtask_id, "task");
      const runs = upsertRun(base.runs, key, (run) => {
        const current = run ?? blankRun(event.agent, event.subtask_id, "task", "");
        const check: EvalCheck = { result: event.result, attempt: event.attempt ?? 1, judge: event.judge ?? null };
        return { ...current, evals: [...current.evals, check] };
      });
      return { ...base, runs };
    }
    case "final":
      return {
        ...base,
        phase: "done",
        final: { answer: event.answer, results: event.results },
        traceUrl: event.trace_url,
      };
    case "clarification":
      return { ...base, phase: "clarification", clarification: event.question };
    case "error":
      return { ...base, phase: "error", error: { message: event.message, agent: event.agent } };
  }
}

export function isTerminal(phase: RunPhase): boolean {
  return phase === "done" || phase === "clarification" || phase === "error" || phase === "cancelled";
}

// ---------------------------------------------------------------------------
// History: rebuild a RunState from a stored ConversationTurn plus the A2A log.
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readFinalPayload(payload: Record<string, unknown>): FinalOutcome | null {
  const answer = payload.answer;
  const results = payload.results;
  if (!isRecord(answer) || typeof answer.answer !== "string") return null;
  return {
    answer: {
      answer: answer.answer,
      claims: Array.isArray(answer.claims) ? (answer.claims as FinalAnswer["claims"]) : [],
      unanswered: Array.isArray(answer.unanswered) ? (answer.unanswered as string[]) : [],
    },
    results: Array.isArray(results) ? (results as AgentResult[]) : [],
  };
}

export function refusalOf(message: A2AMessage): string | null {
  if (message.payload.refused !== true) return null;
  const reason = message.payload.reason ?? message.payload.refusal_reason;
  return typeof reason === "string" ? reason : "Refused";
}

export function feedFromLog(messages: A2AMessage[]): FeedMessage[] {
  return messages.map((message) => {
    const reason = refusalOf(message);
    return { message, refused: reason !== null, refusalReason: reason };
  });
}

export function turnFromHistory(turn: ConversationTurn, messages: FeedMessage[]): Turn {
  const run = emptyRun();
  run.requestId = turn.request_id;
  run.traceUrl = turn.trace_url;
  run.messages = messages;

  const taskMessages = messages.filter((item) => item.message.type === "task" && item.message.sender === "ceo");
  if (taskMessages.length > 0) {
    run.plan = {
      rationale: "",
      subtasks: taskMessages.map((item, index) => ({
        id: typeof item.message.payload.subtask_id === "string" ? item.message.payload.subtask_id : `task_${index + 1}`,
        assigned_to: item.message.recipient,
        instruction: item.message.content,
        depends_on: [],
      })),
    };
  }

  switch (turn.kind) {
    case "final": {
      const final = readFinalPayload(turn.payload);
      if (final) {
        run.final = final;
        run.runs = final.results.map((result) => ({
          ...blankRun(result.agent, result.subtask_id, "task", ""),
          state: result.status,
          result,
        }));
      } else {
        run.final = { answer: { answer: turn.answer ?? "", claims: [], unanswered: [] }, results: [] };
      }
      run.phase = "done";
      break;
    }
    case "clarification":
      run.phase = "clarification";
      run.clarification = turn.answer ?? "";
      break;
    case "error":
      run.phase = "error";
      run.error = { message: turn.answer ?? "The request failed.", agent: null };
      break;
    case "pending":
      run.phase = "running";
      break;
  }

  return { id: turn.request_id, question: turn.question, createdAt: turn.created_at, live: false, run };
}
