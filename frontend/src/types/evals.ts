// Mirrors backend/app/core/judge.py and backend/app/evals/contracts.py exactly.
// Fixed interface for Phase 3: do not edit in the parallel build.

export type Verdict = "pass" | "fail" | "unknown";

export interface DimensionVerdict {
  dimension: string;
  verdict: Verdict;
  score: number; // 0..1
  reasoning: string;
}

export interface JudgeVerdict {
  rubric: string;
  passed: boolean;
  score: number | null;
  dimensions: DimensionVerdict[];
  model: string;
  feedback: string;
  error: string | null;
}

export type Suite = "capability" | "regression";
export type PeerExpectation = "required" | "forbidden" | "any";
export type GraderKind = "code" | "model" | "human";
export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface RequiredFact {
  description: string;
  any_of: string[];
}

export interface ExpectedBehaviour {
  clarification: boolean;
  agents_required: string[];
  agents_forbidden: string[];
  max_agents: number | null;
  peer_messages: PeerExpectation;
  required_facts: RequiredFact[];
  forbidden_facts: RequiredFact[];
  must_report_unanswered: boolean;
  reference_answer: string;
}

export interface EvalTask {
  id: string;
  suite: Suite;
  category: string;
  question: string;
  expected: ExpectedBehaviour;
  graders: string[];
  tags: string[];
  notes: string;
}

export interface Dataset {
  name: string;
  version: string;
  description: string;
  tasks: EvalTask[];
}

export interface GraderResult {
  grader: string;
  kind: GraderKind;
  passed: boolean;
  score: number;
  weight: number;
  reasons: string[];
  judge: JudgeVerdict | null;
  details: Record<string, unknown>;
}

export interface TrialResult {
  trial_id: string;
  run_id: string;
  task_id: string;
  index: number;
  status: "passed" | "failed" | "error";
  score: number;
  passed: boolean;
  graders: GraderResult[];
  question: string;
  final_answer: string | null;
  clarification: string | null;
  agents_planned: string[];
  peer_requests: number;
  refusals: number;
  recoveries: number;
  duration_ms: number;
  llm_calls: number;
  error: string | null;
  trace_url: string | null;
  transcript: Record<string, unknown>[]; // serialized StreamEvents; empty in list responses
  started_at: string;
  finished_at: string | null;
}

export interface TaskSummary {
  task_id: string;
  suite: Suite;
  category: string;
  question: string;
  trials: number;
  passes: number;
  pass_at_k: boolean;
  pass_hat_k: boolean;
  mean_score: number;
  grader_pass_rates: Record<string, number>;
}

export interface RunConfig {
  dataset: string;
  suites: Suite[];
  task_ids: string[];
  trials: number; // 1..5
  judge_enabled: boolean;
  self_eval_recovery: "retry" | "observe";
}

export interface RunSummary {
  run_id: string;
  status: RunStatus;
  config: RunConfig;
  dataset_version: string;
  agent_model: string;
  ceo_model: string;
  judge_model: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  tasks_total: number;
  trials_total: number;
  trials_done: number;
  pass_rate: number | null;
  pass_at_k: number | null;
  pass_hat_k: number | null;
  mean_score: number | null;
  by_suite: Record<string, number>;
  by_category: Record<string, number>;
  grader_pass_rates: Record<string, number>;
  tasks: TaskSummary[];
  error: string | null;
}

export interface RunProgress {
  run_id: string;
  status: RunStatus;
  trials_total: number;
  trials_done: number;
  current_task: string | null;
  message: string;
  updated_at: string;
}

export interface HumanLabel {
  trial_id: string;
  grader: string;
  human_passed: boolean;
  note: string;
  labelled_at: string;
}

export interface HumanLabelRequest {
  trial_id: string;
  grader: string;
  human_passed: boolean;
  note?: string;
}

export interface CalibrationStats {
  labels: number;
  agreement: number | null;
  judge_false_pass: number;
  judge_false_fail: number;
  by_grader: Record<string, number>;
}

export interface SelfEvalRecord {
  request_id: string;
  conversation_id: string | null;
  kind: "eval" | "recovery";
  agent: string;
  subtask_id: string;
  stage: "self" | "independent" | "evidence" | null;
  action: "retry" | "replan" | "clarify" | "give_up" | null;
  passed: boolean | null;
  score: number | null;
  attempt: number;
  payload: Record<string, unknown>; // { reasons?: string[], judge?: JudgeVerdict, feedback?: string }
  created_at: string;
}

export interface SelfEvalStats {
  window_days: number;
  evaluations: number;
  by_stage: Record<string, number>;
  retries: number;
  retry_success_rate: number | null;
  judge_errors: number;
  recent: SelfEvalRecord[];
}
