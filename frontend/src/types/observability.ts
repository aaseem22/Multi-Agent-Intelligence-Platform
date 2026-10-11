// Mirrors the observability models in backend/app/api/schemas.py
// (GET /api/observability/summary, /traces, /traces/{id}).
// Every response carries `enabled`; when false, `reason` says what to fix and the rest is empty.

export interface ObservabilityStatus {
  enabled: boolean;
  reason: string | null;
  /** True when Langfuse is configured but temporarily unreachable (network, rate limit, 5xx). */
  transient?: boolean;
  host: string | null;
}

export interface ObsWindow {
  days: number;
  start: string;
  end: string;
  bucket: "hour" | "day";
}

export interface ObsAgentStat {
  agent: string;
  role: "supervisor" | "department";
  runs: number;
  avg_latency_ms: number | null;
  tool_calls: number;
  failures: number;
}

export interface ObsScoreStat {
  name: string;
  pass_rate: number;
  count: number;
}

export interface ObsEdge {
  source: string;
  target: string;
  /** task = supervisor dispatched a subtask; peer = ask_agent between departments */
  kind: "task" | "peer";
  count: number;
  refusals: number;
  last_at: string | null;
}

export interface ObsBucket {
  bucket: string;
  traces: number;
  avg_latency_ms: number | null;
  tokens: number;
}

export interface ObservabilitySummary extends ObservabilityStatus {
  window: ObsWindow | null;
  supervisor: string | null;
  latency_target_ms: number | null;
  traces: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  total_tokens: number;
  total_cost: number;
  llm_calls: number;
  tool_calls: number;
  peer_calls: number;
  refusals: number;
  error_rate: number;
  success_rate: number | null;
  per_agent: ObsAgentStat[];
  scores: ObsScoreStat[];
  edges: ObsEdge[];
  timeseries: ObsBucket[];
}

export type ObsTraceStatus = "ok" | "partial" | "error";

export interface ObsScoreMark {
  name: string;
  passed: number;
  total: number;
}

export interface ObsTraceMeta {
  id: string;
  name: string | null;
  question: string;
  timestamp: string | null;
  latency_ms: number | null;
  tokens: number;
  cost: number | null;
  agents: string[];
  tags: string[];
  session_id: string | null;
  status: ObsTraceStatus;
  url: string;
}

export interface ObsTraceItem extends ObsTraceMeta {
  peer_calls: number;
  refusals: number;
  scores: ObsScoreMark[];
}

export interface ObservabilityTraces extends ObservabilityStatus {
  traces: ObsTraceItem[];
}

export type ObsObservationKind = "a2a" | "agent" | "llm" | "tool" | "event" | "span";

export interface ObsObservation {
  id: string;
  parent_id: string | null;
  name: string;
  /** Langfuse observation type, upper-case: SPAN, GENERATION, TOOL, AGENT, CHAIN, EVENT... */
  type: string;
  kind: ObsObservationKind;
  depth: number;
  start: string | null;
  end: string | null;
  latency_ms: number | null;
  model: string | null;
  tokens: number;
  level: string | null;
  status_message: string | null;
  failed: boolean;
  /** For agent and a2a spans: agent, mode, subtask_id, hop_count, chain, a2a_message_id */
  metadata: Record<string, unknown>;
}

export interface ObsTraceScore {
  name: string | null;
  value: number | string | null;
  passed: boolean;
  comment: string | null;
  agent: string | null;
  timestamp: string | null;
}

export interface ObsA2AMessage {
  id: string;
  sender: string;
  recipient: string;
  type: string;
  hop_count: number;
  chain: string[];
  refused: boolean;
  reason: string | null;
  content: string;
  created_at: string;
}

export interface ObservabilityTraceDetail extends ObservabilityStatus {
  trace: ObsTraceMeta | null;
  observations: ObsObservation[];
  scores: ObsTraceScore[];
  a2a: ObsA2AMessage[];
}
