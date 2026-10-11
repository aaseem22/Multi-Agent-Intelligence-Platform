// Scripted backend used when VITE_USE_MOCK=true. It plays realistic event streams so the
// UI can be built and demoed without the FastAPI server, Gemini or Langfuse.
//
// Questions it recognises:
//   - "How are we doing?" (or any very short, vague question) -> clarification only
//   - anything containing "simulate error"                     -> an error mid-run
//   - anything else                                            -> the full cross-department run

import type { A2AMessage, A2AMessageType, AgentCard, AgentResult, Evidence, Subtask } from "../types/contracts";
import type {
  A2ALogResponse,
  ChatRequest,
  ConversationDetail,
  ConversationSummary,
  ConversationTurn,
  HealthResponse,
} from "../types/api";
import type { AgentMode, StreamEvent } from "../types/events";
import type { Backend } from "./types";

const OWNER = "demo-owner";
const LANGFUSE_HOST = "https://cloud.langfuse.com";

let sequence = 0;
function nextId(prefix: string): string {
  sequence += 1;
  return `${prefix}_${Date.now().toString(36)}${sequence.toString(36)}`;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

// ---------------------------------------------------------------------------
// Static data
// ---------------------------------------------------------------------------

const AGENT_CARDS: AgentCard[] = [
  {
    name: "ceo",
    department: "Executive",
    description:
      "Supervisor. Interprets stakeholder questions, plans subtasks, dispatches them to department agents and synthesises one answer with evidence.",
    skills: [
      {
        name: "plan",
        description: "Split a cross-department question into subtasks routed by agent cards.",
        example_questions: ["Which technology projects are behind schedule, and is the cause people or budget?"],
      },
      {
        name: "clarify",
        description: "Ask a follow-up question when a request is too vague to plan.",
        example_questions: ["How are we doing?"],
      },
    ],
    owned_data: [],
    accepts_peer_requests: false,
  },
  {
    name: "finance",
    department: "Finance",
    description: "Budgets, spend, and the cost of projects and people. Owns budgets, expenses and payroll.",
    skills: [
      {
        name: "budget_vs_actual",
        description: "Compare quarterly budget with actual spend per project or department.",
        example_questions: ["What is our spend versus budget on Atlas Portal this quarter?"],
      },
      {
        name: "people_cost",
        description: "Monthly payroll cost for employees or everyone allocated to a project.",
        example_questions: ["Which department's people cost grew most last quarter?"],
      },
      {
        name: "top_overruns",
        description: "Rank projects by budget overrun for a period.",
        example_questions: ["Which projects overran their budget in Q2?"],
      },
    ],
    owned_data: ["budgets", "expenses", "payroll"],
    accepts_peer_requests: true,
  },
  {
    name: "hr",
    department: "Human Resources",
    description: "Staffing, allocations, leave and hiring. Owns employees, allocations, leave and open_positions.",
    skills: [
      {
        name: "project_staffing",
        description: "Who is allocated to a project, at what percentage, and in which role.",
        example_questions: ["Who is working on Ledger Sync?"],
      },
      {
        name: "over_allocated",
        description: "Employees whose total allocation exceeds a threshold.",
        example_questions: ["Is anyone allocated above 100%?"],
      },
      {
        name: "leave_overlap",
        description: "Leave that overlaps a project window for its allocated staff.",
        example_questions: ["Did leave affect the Atlas Portal team in August?"],
      },
    ],
    owned_data: ["employees", "allocations", "leave", "open_positions"],
    accepts_peer_requests: true,
  },
  {
    name: "tech",
    department: "Technology",
    description:
      "Project delivery status and repository activity. Owns project delivery fields and read-only GitHub data.",
    skills: [
      {
        name: "project_delivery_status",
        description: "Planned versus expected delivery dates for a project.",
        example_questions: ["Which technology projects are behind schedule?"],
      },
      {
        name: "repo_activity",
        description: "Recent commits, last push, open issues and pull requests for a repository.",
        example_questions: ["Which repo has the most open issues?"],
      },
      {
        name: "stale_repos",
        description: "Repositories with no push for a given number of days.",
        example_questions: ["Which repos have gone quiet for 60 days?"],
      },
    ],
    owned_data: ["projects", "github"],
    accepts_peer_requests: true,
  },
];

// ---------------------------------------------------------------------------
// In-memory conversation store
// ---------------------------------------------------------------------------

interface StoredConversation {
  detail: ConversationDetail;
  a2a: A2AMessage[];
}

const store = new Map<string, StoredConversation>();

function isoMinutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function seedStore(): void {
  const clarifyId = "conv_seed_clarify";
  const clarifyRequest = "req_seed_clarify";
  store.set(clarifyId, {
    detail: {
      id: clarifyId,
      title: "How are we doing?",
      created_at: isoMinutesAgo(60 * 26),
      updated_at: isoMinutesAgo(60 * 26),
      turns: [
        {
          request_id: clarifyRequest,
          question: "How are we doing?",
          kind: "clarification",
          answer: CLARIFICATION_QUESTION,
          payload: {},
          trace_url: `${LANGFUSE_HOST}/project/demo/traces/${clarifyRequest}`,
          created_at: isoMinutesAgo(60 * 26),
        },
      ],
    },
    a2a: [],
  });
}

// ---------------------------------------------------------------------------
// Event builders
// ---------------------------------------------------------------------------

const CLARIFICATION_QUESTION =
  "Could you narrow that down? For example: delivery status of technology projects, budget versus actual for this quarter, or staffing and over-allocation by department.";

interface RunContext {
  requestId: string;
  conversationId: string;
  traceId: string;
  log: A2AMessage[];
}

function base(ctx: RunContext) {
  return { request_id: ctx.requestId, conversation_id: ctx.conversationId, timestamp: new Date().toISOString() };
}

function a2a(
  ctx: RunContext,
  sender: string,
  recipient: string,
  type: A2AMessageType,
  content: string,
  hop: number,
  chain: string[],
  payload: Record<string, unknown> = {},
): A2AMessage {
  const message: A2AMessage = {
    id: nextId("msg"),
    request_id: ctx.requestId,
    trace_id: ctx.traceId,
    sender,
    recipient,
    type,
    content,
    payload,
    hop_count: hop,
    chain,
    created_at: new Date().toISOString(),
  };
  ctx.log.push(message);
  return message;
}

function peerEvent(ctx: RunContext, message: A2AMessage, refusalReason: string | null = null): StreamEvent {
  return {
    ...base(ctx),
    type: "peer_message",
    message,
    refused: refusalReason !== null,
    refusal_reason: refusalReason,
  };
}

function started(ctx: RunContext, agent: string, subtaskId: string, mode: AgentMode, instruction: string): StreamEvent {
  return { ...base(ctx), type: "agent_started", agent, subtask_id: subtaskId, mode, instruction };
}

function tool(ctx: RunContext, agent: string, subtaskId: string, name: string, args: Record<string, unknown>): StreamEvent {
  return { ...base(ctx), type: "tool_call", agent, subtask_id: subtaskId, tool: name, args };
}

function resultEvent(ctx: RunContext, mode: AgentMode, result: AgentResult): StreamEvent {
  return { ...base(ctx), type: "agent_result", mode, result };
}

function evals(ctx: RunContext, agent: string, subtaskId: string): StreamEvent[] {
  return (["self", "independent", "evidence"] as const).map((stage) => ({
    ...base(ctx),
    type: "eval_result" as const,
    agent,
    subtask_id: subtaskId,
    result: {
      passed: true,
      stage,
      reasons: stage === "evidence" ? ["Result cites at least one evidence record."] : ["Stub: evaluation not implemented in Phase 1."],
      score: null,
    },
  }));
}

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------

type Step = [delayMs: number, build: () => StreamEvent | StreamEvent[]];

interface ScenarioOutcome {
  steps: Step[];
  finish: () => Pick<ConversationTurn, "kind" | "answer" | "payload" | "trace_url">;
}

function clarificationScenario(ctx: RunContext): ScenarioOutcome {
  return {
    steps: [[900, () => ({ ...base(ctx), type: "clarification", question: CLARIFICATION_QUESTION })]],
    finish: () => ({ kind: "clarification", answer: CLARIFICATION_QUESTION, payload: {}, trace_url: traceUrl(ctx) }),
  };
}

function errorScenario(ctx: RunContext): ScenarioOutcome {
  const subtask: Subtask = {
    id: "st_1",
    assigned_to: "tech",
    instruction: "List projects with delivery risk.",
    depends_on: [],
  };
  const message = "Gemini rate limit: retries exhausted after 4 attempts (429 RESOURCE_EXHAUSTED).";
  return {
    steps: [
      [700, () => ({ ...base(ctx), type: "plan", subtasks: [subtask], rationale: "Delivery risk is owned by Tech." })],
      [300, () => peerEvent(ctx, a2a(ctx, "ceo", "tech", "task", subtask.instruction, 0, ["ceo"], { subtask_id: subtask.id }))],
      [300, () => started(ctx, "tech", subtask.id, "task", subtask.instruction)],
      [900, () => tool(ctx, "tech", subtask.id, "list_projects", { status: "active" })],
      [1200, () => ({ ...base(ctx), type: "error", message, agent: "tech" })],
    ],
    finish: () => ({ kind: "error", answer: message, payload: {}, trace_url: traceUrl(ctx) }),
  };
}

function traceUrl(ctx: RunContext): string {
  return `${LANGFUSE_HOST}/project/demo/traces/${ctx.traceId}`;
}

function crossDepartmentScenario(ctx: RunContext): ScenarioOutcome {
  const subtasks: Subtask[] = [
    {
      id: "st_tech",
      assigned_to: "tech",
      instruction:
        "Identify technology projects that are behind schedule (planned end vs status) and check recent repository activity for each.",
      depends_on: [],
    },
    {
      id: "st_fin",
      assigned_to: "finance",
      instruction: "Report budget versus actual for every Engineering project in 2026-Q3 and flag overruns above 10%.",
      depends_on: [],
    },
    {
      id: "st_hr",
      assigned_to: "hr",
      instruction: "List Engineering staff allocated above 100% and any leave overlapping Q3 project windows.",
      depends_on: [],
    },
  ];

  const repo = `${OWNER}/ledger-sync`;
  const since = "2026-06-29";

  // Messages are created lazily inside steps so their timestamps follow playback.
  let techPeerRequest: A2AMessage | undefined;
  let hrPeerRequest: A2AMessage | undefined;

  const financePeerResult: AgentResult = {
    agent: "finance",
    subtask_id: "st_tech",
    status: "ok",
    answer: "Monthly payroll for the three Ledger Sync engineers is INR 7.9 lakh; unchanged since Q2.",
    evidence: [
      {
        source_type: "db",
        source_ref: "payroll:employee_id=12,18,23;period=2026-08",
        summary: "August payroll rows for employees 12, 18 and 23.",
        data: { total_inr: 790000, rows: 3 },
      },
    ],
    peer_messages: [],
    error: null,
  };

  const hrEvidence: Evidence[] = [
    {
      source_type: "db",
      source_ref: "allocations:employee_id=12",
      summary: "Priya Nair (lead, Ledger Sync) is allocated 140% across three projects.",
      data: { employee: "Priya Nair", total_pct: 140, projects: [7, 3, 9] },
    },
    {
      source_type: "db",
      source_ref: "leave:id=31,34",
      summary: "Two of three Ledger Sync engineers were on overlapping leave 4-22 Aug.",
      data: { employees: [18, 23], start: "2026-08-04", end: "2026-08-22" },
    },
  ];

  const hrPeerResult = (): AgentResult => ({
    agent: "hr",
    subtask_id: "st_tech",
    status: "ok",
    answer:
      "Ledger Sync has 3 people: Priya Nair (lead, 140% total allocation), Arjun Mehta and Kavya Rao. Arjun and Kavya had overlapping leave 4-22 Aug. Finance confirms their payroll cost is flat.",
    evidence: [
      ...hrEvidence,
      {
        source_type: "peer",
        source_ref: `peer:finance:${hrPeerRequest?.id ?? "msg"}`,
        summary: "Finance: payroll for the three engineers is flat at INR 7.9 lakh/month.",
        data: null,
      },
    ],
    peer_messages: hrPeerRequest ? [hrPeerRequest.id] : [],
    error: null,
  });

  const techEvidence = (): Evidence[] => [
    {
      source_type: "db",
      source_ref: "projects:id=7",
      summary: "Ledger Sync planned end 2026-08-24, status still 'in_progress' (34 days late).",
      data: { planned_end: "2026-08-24", status: "in_progress" },
    },
    {
      source_type: "github",
      source_ref: `github:repos/${repo}/commits?since=${since}`,
      summary: "Last push to ledger-sync on 2026-07-12; 0 commits since.",
      data: { commits: 0, last_push: "2026-07-12T09:41:00Z" },
    },
    {
      source_type: "db",
      source_ref: "projects:id=3",
      summary: "Atlas Portal planned end 2026-09-15, status 'in_progress' (12 days late).",
      data: { planned_end: "2026-09-15", status: "in_progress" },
    },
    {
      source_type: "github",
      source_ref: `github:repos/${OWNER}/atlas-portal/issues?state=open`,
      summary: "Atlas Portal has 23 open issues, 9 labelled 'blocked-on-vendor'.",
      data: { open: 23, blocked_on_vendor: 9 },
    },
    {
      source_type: "peer",
      source_ref: `peer:hr:${techPeerRequest?.id ?? "msg"}`,
      summary: "HR: Ledger Sync lead over-allocated at 140%, two engineers on overlapping leave in August.",
      data: null,
    },
  ];

  const techResult = (): AgentResult => ({
    agent: "tech",
    subtask_id: "st_tech",
    status: "ok",
    answer:
      "Two projects are behind schedule. Ledger Sync (id 7) is 34 days late with no push since 12 July; HR reports its lead is at 140% allocation and two engineers overlapped on leave. Atlas Portal (id 3) is 12 days late with active commits but 9 issues blocked on a vendor.",
    evidence: techEvidence(),
    peer_messages: [techPeerRequest?.id, hrPeerRequest?.id].filter((id): id is string => Boolean(id)),
    error: null,
  });

  const financeResult: AgentResult = {
    agent: "finance",
    subtask_id: "st_fin",
    status: "partial",
    answer:
      "Atlas Portal has spent 131% of its Q3 budget, mostly external contractors. Ledger Sync is at 82% of budget. Vendor-level breakdown for Atlas Portal is not available.",
    evidence: [
      {
        source_type: "db",
        source_ref: "budgets:id=27",
        summary: "Ledger Sync Q3 budget INR 42 lakh; actual INR 34.4 lakh (82%).",
        data: { budget: 4200000, actual: 3444000, pct: 82 },
      },
      {
        source_type: "db",
        source_ref: "budgets:id=19",
        summary: "Atlas Portal Q3 budget INR 55 lakh; actual INR 72.1 lakh (131%).",
        data: { budget: 5500000, actual: 7205000, pct: 131 },
      },
      {
        source_type: "db",
        source_ref: "expenses:project_id=3;category=contractors;period=2026-Q3",
        summary: "Contractor spend on Atlas Portal is INR 29.8 lakh, 41% of Q3 actuals.",
        data: { contractors: 2980000, share_pct: 41 },
      },
    ],
    peer_messages: [],
    error: null,
  };

  const hrResult: AgentResult = {
    agent: "hr",
    subtask_id: "st_hr",
    status: "ok",
    answer:
      "One Engineering employee is above 100%: Priya Nair at 140%. Atlas Portal staffing is at plan (5 people, none over-allocated).",
    evidence: [
      ...hrEvidence,
      {
        source_type: "db",
        source_ref: "allocations:project_id=3",
        summary: "Atlas Portal has 5 allocated staff, all at or below 100%.",
        data: { staff: 5, max_pct: 100 },
      },
    ],
    peer_messages: [],
    error: null,
  };

  const finalAnswer = () => {
    const tech = techResult();
    return {
      answer:
        "Two technology projects are behind schedule, and they fail for different reasons. Ledger Sync is a people problem: it is within budget, but its lead is heavily over-allocated and two of its three engineers were on leave at the same time, after which the repository went quiet. Atlas Portal is a budget problem: staffing is at plan, but contractor spend has pushed it to 131% of its Q3 budget and much of its open work is blocked on a vendor.",
      claims: [
        {
          text: "Ledger Sync is 34 days past its planned end and its repository has had no push since 12 July.",
          evidence_refs: ["projects:id=7", `github:repos/${repo}/commits?since=${since}`],
          agents: ["tech"],
        },
        {
          text: "Its lead, Priya Nair, is allocated at 140%, and two of its three engineers had overlapping leave from 4 to 22 August.",
          evidence_refs: [tech.evidence[4].source_ref, "allocations:employee_id=12", "leave:id=31,34"],
          agents: ["tech", "hr"],
        },
        {
          text: "Ledger Sync has spent 82% of its Q3 budget, so budget is not the cause of its delay.",
          evidence_refs: ["budgets:id=27"],
          agents: ["finance"],
        },
        {
          text: "Atlas Portal is 12 days late with 9 issues blocked on a vendor, while its staffing is at plan.",
          evidence_refs: ["projects:id=3", `github:repos/${OWNER}/atlas-portal/issues?state=open`, "allocations:project_id=3"],
          agents: ["tech", "hr"],
        },
        {
          text: "Atlas Portal has spent 131% of its Q3 budget, with contractors making up 41% of actuals.",
          evidence_refs: ["budgets:id=19", "expenses:project_id=3;category=contractors;period=2026-Q3"],
          agents: ["finance"],
        },
      ],
      unanswered: [
        "Finance could not break Atlas Portal contractor spend down by vendor: there are no vendor-level expense records for Q3.",
        "Finance's follow-up to Tech about who authored recent Ledger Sync commits was refused by the hop limit, so commit authorship was not cross-checked against payroll.",
      ],
    };
  };

  const steps: Step[] = [
    [
      800,
      () => ({
        ...base(ctx),
        type: "plan",
        subtasks,
        rationale:
          "Delivery status belongs to Tech, cost to Finance and staffing to HR. The three subtasks are independent and can run in parallel.",
      }),
    ],
    [250, () => subtasks.map((s) => peerEvent(ctx, a2a(ctx, "ceo", s.assigned_to, "task", s.instruction, 0, ["ceo"], { subtask_id: s.id })))],
    [200, () => subtasks.map((s) => started(ctx, s.assigned_to, s.id, "task", s.instruction))],
    [600, () => tool(ctx, "tech", "st_tech", "list_projects", { status: "in_progress" })],
    [300, () => tool(ctx, "finance", "st_fin", "budget_vs_actual", { period: "2026-Q3", department_id: 1 })],
    [300, () => tool(ctx, "hr", "st_hr", "over_allocated", { threshold_pct: 100 })],
    [500, () => tool(ctx, "tech", "st_tech", "project_delivery_status", { project_id: 7 })],
    [400, () => tool(ctx, "tech", "st_tech", "repo_activity", { repo, since })],
    [400, () => tool(ctx, "finance", "st_fin", "expenses_by_category", { project_id: 3, start: "2026-07-01", end: "2026-09-30" })],
    [
      500,
      () => {
        techPeerRequest = a2a(
          ctx,
          "tech",
          "hr",
          "peer_request",
          "Ledger Sync (project 7) has had no push since 12 July. Who is allocated to it, and did anyone have leave overlapping July to August?",
          1,
          ["ceo", "tech"],
        );
        return peerEvent(ctx, techPeerRequest);
      },
    ],
    [250, () => started(ctx, "hr", "st_tech", "peer", techPeerRequest?.content ?? "")],
    [300, () => tool(ctx, "hr", "st_hr", "leave_overlap", { project_id: 3, start: "2026-07-01", end: "2026-09-30" })],
    [400, () => tool(ctx, "hr", "st_tech", "project_staffing", { project_id: 7 })],
    [400, () => tool(ctx, "hr", "st_tech", "leave_overlap", { project_id: 7, start: "2026-07-01", end: "2026-08-31" })],
    [
      500,
      () => {
        hrPeerRequest = a2a(
          ctx,
          "hr",
          "finance",
          "peer_request",
          "What is the monthly payroll cost for employees 12, 18 and 23, and has it changed since Q2?",
          2,
          ["ceo", "tech", "hr"],
        );
        return peerEvent(ctx, hrPeerRequest);
      },
    ],
    [250, () => started(ctx, "finance", "st_tech", "peer", hrPeerRequest?.content ?? "")],
    [400, () => tool(ctx, "finance", "st_tech", "people_cost", { employee_ids: [12, 18, 23], period: "2026-08" })],
    [
      500,
      () => {
        const reason = "Hop limit reached: hop_count 3 would exceed MAX_PEER_HOPS=2.";
        const refused = a2a(
          ctx,
          "finance",
          "tech",
          "peer_request",
          "Which of employees 12, 18 and 23 authored commits on ledger-sync this quarter?",
          3,
          ["ceo", "tech", "hr", "finance"],
          { refused: true, reason },
        );
        return peerEvent(ctx, refused, reason);
      },
    ],
    [
      400,
      () => {
        const response = a2a(ctx, "finance", "hr", "peer_response", financePeerResult.answer, 2, ["ceo", "tech", "hr"], {
          in_reply_to: hrPeerRequest?.id,
          status: financePeerResult.status,
        });
        return [resultEvent(ctx, "peer", financePeerResult), peerEvent(ctx, response)];
      },
    ],
    [300, () => tool(ctx, "finance", "st_fin", "top_overruns", { period: "2026-Q3", n: 3 })],
    [
      500,
      () => {
        const result = hrPeerResult();
        const response = a2a(ctx, "hr", "tech", "peer_response", result.answer, 1, ["ceo", "tech"], {
          in_reply_to: techPeerRequest?.id,
          status: result.status,
        });
        return [resultEvent(ctx, "peer", result), peerEvent(ctx, response)];
      },
    ],
    [
      500,
      () => [
        resultEvent(ctx, "task", hrResult),
        peerEvent(ctx, a2a(ctx, "hr", "ceo", "result", hrResult.answer, 0, ["ceo", "hr"], { subtask_id: "st_hr" })),
      ],
    ],
    [300, () => evals(ctx, "hr", "st_hr")],
    [400, () => tool(ctx, "tech", "st_tech", "open_issues", { repo: `${OWNER}/atlas-portal` })],
    [
      600,
      () => [
        resultEvent(ctx, "task", financeResult),
        peerEvent(ctx, a2a(ctx, "finance", "ceo", "result", financeResult.answer, 0, ["ceo", "finance"], { subtask_id: "st_fin" })),
      ],
    ],
    [300, () => evals(ctx, "finance", "st_fin")],
    [
      700,
      () => {
        const result = techResult();
        return [
          resultEvent(ctx, "task", result),
          peerEvent(ctx, a2a(ctx, "tech", "ceo", "result", result.answer, 0, ["ceo", "tech"], { subtask_id: "st_tech" })),
        ];
      },
    ],
    [300, () => evals(ctx, "tech", "st_tech")],
    [
      1400,
      () => ({
        ...base(ctx),
        type: "final",
        answer: finalAnswer(),
        results: [techResult(), financeResult, hrResult],
        trace_url: traceUrl(ctx),
      }),
    ],
  ];

  return {
    steps,
    finish: () => {
      const answer = finalAnswer();
      return {
        kind: "final",
        answer: answer.answer,
        payload: { answer, results: [techResult(), financeResult, hrResult] },
        trace_url: traceUrl(ctx),
      };
    },
  };
}

const VAGUE = /^(how are (we|things) (doing|going)\??|status\??|update\??|any news\??)$/i;

function pickScenario(message: string, ctx: RunContext): ScenarioOutcome {
  const text = message.trim();
  if (/simulate error/i.test(text)) return errorScenario(ctx);
  if (VAGUE.test(text) || text.split(/\s+/).length <= 2) return clarificationScenario(ctx);
  return crossDepartmentScenario(ctx);
}

function titleFrom(message: string): string {
  const text = message.trim().replace(/\s+/g, " ");
  return text.length > 60 ? `${text.slice(0, 57)}...` : text;
}

async function* streamChat(request: ChatRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const conversationId = request.conversation_id ?? nextId("conv");
  const requestId = nextId("req");
  const ctx: RunContext = { requestId, conversationId, traceId: nextId("trace"), log: [] };
  const createdAt = new Date().toISOString();

  let conversation = store.get(conversationId);
  if (!conversation) {
    conversation = {
      detail: { id: conversationId, title: titleFrom(request.message), created_at: createdAt, updated_at: createdAt, turns: [] },
      a2a: [],
    };
    store.set(conversationId, conversation);
  }
  const turn: ConversationTurn = {
    request_id: requestId,
    question: request.message,
    kind: "pending",
    answer: null,
    payload: {},
    trace_url: null,
    created_at: createdAt,
  };
  conversation.detail.turns.push(turn);

  const scenario = pickScenario(request.message, ctx);
  for (const [delay, build] of scenario.steps) {
    await sleep(delay, signal);
    const built = build();
    for (const event of Array.isArray(built) ? built : [built]) yield event;
  }

  Object.assign(turn, scenario.finish());
  conversation.a2a.push(...ctx.log);
  conversation.detail.updated_at = new Date().toISOString();
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

async function respond<T>(value: T, signal?: AbortSignal, delay = 350): Promise<T> {
  await sleep(delay, signal);
  return clone(value);
}

seedStore();

export const mockBackend: Backend = {
  mode: "mock",
  streamChat,
  // Scripted runs stop when their stream is aborted, so there is nothing to cancel server-side.
  cancelChat: async () => {},
  getAgents: (signal) => respond(AGENT_CARDS, signal),
  getConversations: (signal) => {
    const list: ConversationSummary[] = [...store.values()]
      .map(({ detail }) => ({ id: detail.id, title: detail.title, created_at: detail.created_at, updated_at: detail.updated_at }))
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    return respond(list, signal, 250);
  },
  getConversation: async (id, signal) => {
    const found = store.get(id);
    if (!found) {
      await sleep(250, signal);
      throw new Error(`Conversation ${id} was not found.`);
    }
    return respond(found.detail, signal);
  },
  getConversationA2A: (id, signal) => respond<A2ALogResponse>(store.get(id)?.a2a ?? [], signal),
  getHealth: (signal) =>
    respond<HealthResponse>(
      { status: "ok", database: true, github_token: true, langfuse: true, agents: AGENT_CARDS.map((c) => c.name) },
      signal,
      150,
    ),
};
