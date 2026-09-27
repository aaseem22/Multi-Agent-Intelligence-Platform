// Scripted observability data for mock mode (VITE_USE_MOCK=true): 4 agents over 7 days,
// 20 traces, and one fully detailed trace with a nested a2a span and a refused peer call.
//
// Add ?obs=disabled, ?obs=empty, ?obs=error or ?obs=slow to the URL to preview the other states.

import type {
  ObsA2AMessage,
  ObsAgentStat,
  ObsBucket,
  ObsEdge,
  ObsObservation,
  ObsObservationKind,
  ObsScoreMark,
  ObsTraceItem,
  ObsTraceScore,
  ObsTraceStatus,
  ObservabilitySummary,
  ObservabilityTraceDetail,
  ObservabilityTraces,
} from "../types/observability";
import type { ObservabilityClient } from "./observability";

const HOST = "https://cloud.langfuse.com";
const PROJECT = "/project/demo-orchestration";
const DEPARTMENTS = ["finance", "hr", "tech"] as const;
const MODEL = "gemini-3.5-flash-lite";
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const SCORE_NAMES = ["eval_evidence", "eval_independent", "eval_self"];

type Scenario = "normal" | "disabled" | "empty" | "error" | "slow";

function scenario(): Scenario {
  const value = new URLSearchParams(window.location.search).get("obs");
  return value === "disabled" || value === "empty" || value === "error" || value === "slow"
    ? value
    : "normal";
}

function mulberry32(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const QUESTIONS: { q: string; agents: string[]; peers: [string, string][]; refused?: [string, string] }[] = [
  {
    q: "Which technology projects are behind schedule, and is the cause people or budget?",
    agents: ["tech", "hr", "finance"],
    peers: [["tech", "hr"]],
    refused: ["hr", "tech"],
  },
  { q: "What is our spend versus budget on Ledger Sync this quarter?", agents: ["finance"], peers: [] },
  {
    q: "Who is working on the repo with the most open issues, and are they over-allocated?",
    agents: ["tech"],
    peers: [["tech", "hr"]],
  },
  { q: "Which department's people cost grew most last quarter?", agents: ["finance"], peers: [["finance", "hr"]] },
  { q: "List repositories with no push in the last 60 days.", agents: ["tech"], peers: [] },
  { q: "How many open positions does Engineering have, and how old are they?", agents: ["hr"], peers: [] },
  {
    q: "Is the Data Platform project understaffed relative to its budget?",
    agents: ["hr", "finance"],
    peers: [["hr", "finance"]],
  },
  { q: "Top three budget overruns this quarter and their owners.", agents: ["finance"], peers: [["finance", "hr"]] },
  {
    q: "Which stalled repos have leads on leave this month?",
    agents: ["tech"],
    peers: [["tech", "hr"]],
    refused: ["tech", "hr"],
  },
  { q: "Headcount by department as of today.", agents: ["hr"], peers: [] },
  { q: "What is the spend trend on Operations tooling since April?", agents: ["finance"], peers: [] },
  { q: "Which open pull requests have been waiting longest for review?", agents: ["tech"], peers: [] },
  {
    q: "Compare people cost and delivery status for the Payments revamp.",
    agents: ["finance", "tech"],
    peers: [["tech", "hr"]],
  },
  { q: "Who is over 110% allocated right now?", agents: ["hr"], peers: [] },
  {
    q: "Is the mobile app delay caused by leave overlap or by scope?",
    agents: ["tech", "hr"],
    peers: [["tech", "hr"]],
  },
  { q: "Expenses by category for the Search project last quarter.", agents: ["finance"], peers: [] },
  { q: "Which projects are healthy on both budget and staffing?", agents: ["finance", "hr"], peers: [] },
  { q: "Recent commit activity across Data department repos.", agents: ["tech"], peers: [] },
  {
    q: "Which contractors cost the most on delayed projects?",
    agents: ["finance", "tech"],
    peers: [["finance", "hr"]],
    refused: ["finance", "hr"],
  },
  { q: "Summarise open issues on the analytics pipeline repo.", agents: ["tech"], peers: [] },
];

interface GeneratedTrace {
  item: ObsTraceItem;
  toolCalls: Record<string, number>;
  runLatency: Record<string, number>;
  failed: string[];
  llmCalls: number;
  ceoLatency: number;
}

function iso(ms: number): string {
  return new Date(ms).toISOString();
}

function generate(now: number): GeneratedTrace[] {
  const random = mulberry32(42);
  return QUESTIONS.map((spec, index) => {
    // Newest first, spread across 7 days with more traffic in recent days.
    const age = index === 0 ? 0.35 * HOUR : Math.pow(index / QUESTIONS.length, 1.25) * 6.8 * DAY + random() * 2 * HOUR;
    const start = now - age;
    const width = spec.agents.length + spec.peers.length;
    const latency = Math.round(14_000 + width * 9_000 + random() * 16_000);
    const tokens = Math.round(4_200 + width * 3_100 + random() * 3_800);
    const failed = index === 6 ? ["finance"] : [];
    const errored = index === 11;
    const evidenceFail = index === 13;
    const status: ObsTraceStatus = errored ? "error" : failed.length || evidenceFail ? "partial" : "ok";
    const runs = spec.agents.length;
    const scores: ObsScoreMark[] = SCORE_NAMES.map((name) => ({
      name,
      passed: name === "eval_evidence" && evidenceFail ? runs - 1 : runs,
      total: runs,
    }));
    const toolCalls: Record<string, number> = {};
    const runLatency: Record<string, number> = {};
    for (const agent of [...spec.agents, ...spec.peers.map((p) => p[1])]) {
      toolCalls[agent] = (toolCalls[agent] ?? 0) + 1 + Math.round(random() * 3);
      runLatency[agent] = Math.round(latency * (0.35 + random() * 0.35));
    }
    const item: ObsTraceItem = {
      id: `a1b2c3${index.toString(16).padStart(2, "0")}9f0e4d7c8b6a5${(index * 7919).toString(16).padStart(6, "0")}`.slice(0, 32),
      name: "stakeholder_request",
      question: spec.q,
      timestamp: iso(start),
      latency_ms: latency,
      tokens,
      cost: Math.round(tokens * 0.000_000_3 * 1e6) / 1e6,
      agents: [...new Set([...spec.agents, ...spec.peers.flat()])].sort(),
      tags: [...spec.agents].sort(),
      session_id: `conv_${(index * 104729).toString(36)}`,
      status,
      peer_calls: spec.peers.length,
      refusals: spec.refused ? 1 : 0,
      scores,
      url: "",
    };
    item.url = `${HOST}${PROJECT}/traces/${item.id}`;
    return {
      item,
      toolCalls,
      runLatency,
      failed,
      llmCalls: 2 + spec.agents.length * 2 + spec.peers.length * 2,
      ceoLatency: Math.round(latency * 0.28),
    };
  });
}

function mean(values: number[]): number | null {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

function summarise(traces: GeneratedTrace[], now: number, days: number): ObservabilitySummary {
  const inWindow = traces.filter((t) => now - Date.parse(t.item.timestamp ?? "") <= days * DAY);
  const latencies = inWindow.map((t) => t.item.latency_ms ?? 0).sort((a, b) => a - b);
  const hourly = days <= 2;
  const step = hourly ? HOUR : DAY;
  const startMs = now - days * DAY;
  const first = new Date(startMs);
  if (hourly) first.setMinutes(0, 0, 0);
  else first.setHours(0, 0, 0, 0);
  const buckets: ObsBucket[] = [];
  for (let cursor = first.getTime(); cursor <= now; cursor += step) {
    const members = inWindow.filter((t) => {
      const at = Date.parse(t.item.timestamp ?? "");
      return at >= cursor && at < cursor + step;
    });
    buckets.push({
      bucket: iso(cursor),
      traces: members.length,
      avg_latency_ms: mean(members.map((m) => m.item.latency_ms ?? 0)),
      tokens: members.reduce((sum, m) => sum + m.item.tokens, 0),
    });
  }

  const agentRuns = new Map<string, { runs: number; latency: number[]; tools: number; failures: number }>();
  const edges = new Map<string, ObsEdge>();
  const bump = (source: string, target: string, kind: ObsEdge["kind"], at: string, refused = false) => {
    const key = `${kind}:${source}:${target}`;
    const edge = edges.get(key) ?? { source, target, kind, count: 0, refusals: 0, last_at: null };
    if (refused) edge.refusals += 1;
    else edge.count += 1;
    if (!edge.last_at || at > edge.last_at) edge.last_at = at;
    edges.set(key, edge);
  };
  for (const trace of inWindow) {
    const spec = QUESTIONS.find((q) => q.q === trace.item.question);
    if (!spec) continue;
    const at = trace.item.timestamp ?? iso(now);
    for (const [agent, tools] of Object.entries(trace.toolCalls)) {
      const row = agentRuns.get(agent) ?? { runs: 0, latency: [], tools: 0, failures: 0 };
      const runs = spec.agents.filter((a) => a === agent).length + spec.peers.filter((p) => p[1] === agent).length;
      row.runs += runs;
      row.latency.push(trace.runLatency[agent]);
      row.tools += tools;
      row.failures += trace.failed.includes(agent) ? 1 : 0;
      agentRuns.set(agent, row);
    }
    for (const agent of spec.agents) bump("ceo", agent, "task", at);
    for (const [source, target] of spec.peers) bump(source, target, "peer", at);
    if (spec.refused) bump(spec.refused[0], spec.refused[1], "peer", at, true);
  }

  const perAgent: ObsAgentStat[] = [
    {
      agent: "ceo",
      role: "supervisor",
      runs: inWindow.length,
      avg_latency_ms: mean(inWindow.map((t) => t.ceoLatency)),
      tool_calls: 0,
      failures: inWindow.filter((t) => t.item.status === "error").length,
    },
    ...DEPARTMENTS.filter((name) => agentRuns.has(name)).map((name) => {
      const row = agentRuns.get(name)!;
      return {
        agent: name,
        role: "department" as const,
        runs: row.runs,
        avg_latency_ms: mean(row.latency),
        tool_calls: row.tools,
        failures: row.failures,
      };
    }),
  ];

  const scoreTotals = new Map<string, { passed: number; total: number }>();
  for (const trace of inWindow) {
    for (const mark of trace.item.scores) {
      const total = scoreTotals.get(mark.name) ?? { passed: 0, total: 0 };
      total.passed += mark.passed;
      total.total += mark.total;
      scoreTotals.set(mark.name, total);
    }
  }
  const count = inWindow.length;
  return {
    enabled: true,
    reason: null,
    host: HOST,
    window: { days, start: iso(startMs), end: iso(now), bucket: hourly ? "hour" : "day" },
    supervisor: "ceo",
    latency_target_ms: 45_000,
    traces: count,
    avg_latency_ms: mean(latencies),
    p95_latency_ms: latencies.length ? latencies[Math.max(Math.ceil(0.95 * latencies.length) - 1, 0)] : null,
    total_tokens: inWindow.reduce((sum, t) => sum + t.item.tokens, 0),
    total_cost: Math.round(inWindow.reduce((sum, t) => sum + (t.item.cost ?? 0), 0) * 1e6) / 1e6,
    llm_calls: inWindow.reduce((sum, t) => sum + t.llmCalls, 0),
    tool_calls: [...agentRuns.values()].reduce((sum, r) => sum + r.tools, 0),
    peer_calls: inWindow.reduce((sum, t) => sum + t.item.peer_calls, 0),
    refusals: inWindow.reduce((sum, t) => sum + t.item.refusals, 0),
    error_rate: count ? inWindow.filter((t) => t.item.status === "error").length / count : 0,
    success_rate: count ? inWindow.filter((t) => t.item.status === "ok").length / count : null,
    per_agent: perAgent,
    scores: [...scoreTotals.entries()].map(([name, { passed, total }]) => ({
      name,
      pass_rate: total ? passed / total : 0,
      count: total,
    })),
    edges: [...edges.values()].sort((a, b) => a.kind.localeCompare(b.kind) || a.source.localeCompare(b.source)),
    timeseries: buckets,
  };
}

// ---------------------------------------------------------------------------
// The detailed trace: a Tech run that asks HR, HR's attempt to ask Tech back is refused.
// ---------------------------------------------------------------------------

interface Node {
  name: string;
  kind: ObsObservationKind;
  type: string;
  from: number;
  to: number;
  tokens?: number;
  metadata?: Record<string, unknown>;
  level?: string;
  status?: string;
  failed?: boolean;
  children?: Node[];
}

const gen = (from: number, to: number, tokens: number): Node => ({
  name: "ChatGoogleGenerativeAI",
  kind: "llm",
  type: "GENERATION",
  from,
  to,
  tokens,
});
const tool = (name: string, from: number, to: number, extra: Partial<Node> = {}): Node => ({
  name,
  kind: "tool",
  type: "TOOL",
  from,
  to,
  ...extra,
});
const span = (name: string, from: number, to: number, children: Node[] = []): Node => ({
  name,
  kind: "span",
  type: "CHAIN",
  from,
  to,
  children,
});

const DETAIL_TREE: Node = {
  name: "stakeholder_request",
  kind: "span",
  type: "AGENT",
  from: 0,
  to: 61.8,
  children: [
    span("intake", 0.02, 0.21),
    span("plan", 0.22, 4.1, [gen(0.3, 4.0, 1840)]),
    span("dispatch", 4.11, 4.18),
    span("run_agent", 4.2, 39.6, [
      {
        name: "agent:tech",
        kind: "agent",
        type: "AGENT",
        from: 4.25,
        to: 39.5,
        metadata: { agent: "tech", mode: "task", subtask_id: "t1", hop_count: 0, chain: [] },
        children: [
          gen(4.3, 7.1, 2210),
          tool("stale_repos", 7.2, 7.9),
          tool("repo_activity", 8.0, 9.1),
          gen(9.2, 11.8, 2480),
          tool("ask_agent", 11.9, 30.2, {
            children: [
              {
                name: "a2a:tech->hr",
                kind: "a2a",
                type: "AGENT",
                from: 12.0,
                to: 30.0,
                metadata: {
                  agent: "hr",
                  mode: "peer",
                  subtask_id: "t1/hr",
                  hop_count: 1,
                  chain: ["tech"],
                  a2a_message_id: "msg_7c1e0b2a9d43f610",
                },
                children: [
                  gen(12.1, 14.6, 1960),
                  tool("project_staffing", 14.7, 15.4),
                  tool("leave_overlap", 15.5, 16.3),
                  tool("ask_agent", 16.4, 16.5, {
                    level: "WARNING",
                    status: "REFUSED: cycle detected: 'tech' is already in the chain tech -> hr",
                  }),
                  gen(16.6, 29.8, 2750),
                ],
              },
            ],
          }),
          gen(30.4, 39.2, 3120),
        ],
      },
      span("self_check", 39.51, 39.55),
    ]),
    span("run_agent", 4.2, 26.4, [
      {
        name: "agent:finance",
        kind: "agent",
        type: "AGENT",
        from: 4.26,
        to: 26.3,
        metadata: { agent: "finance", mode: "task", subtask_id: "t2", hop_count: 0, chain: [] },
        children: [
          gen(4.4, 9.8, 2060),
          tool("budget_vs_actual", 9.9, 10.6),
          tool("top_overruns", 10.7, 11.2),
          gen(11.3, 26.1, 2890),
        ],
      },
      span("self_check", 26.31, 26.34),
    ]),
    span("run_agent", 4.2, 33.1, [
      {
        name: "agent:hr",
        kind: "agent",
        type: "AGENT",
        from: 4.27,
        to: 33.0,
        metadata: { agent: "hr", mode: "task", subtask_id: "t3", hop_count: 0, chain: [] },
        children: [
          gen(4.5, 13.2, 1990),
          tool("over_allocated", 13.3, 13.9),
          tool("project_staffing", 14.0, 14.6),
          gen(14.7, 32.8, 2610),
        ],
      },
      span("self_check", 33.01, 33.04),
    ]),
    span("eval_gate", 39.62, 39.7),
    span("eval_gate", 26.42, 26.5),
    span("eval_gate", 33.12, 33.2),
    span("collect", 39.72, 39.75),
    span("synthesise", 39.8, 61.2, [gen(39.9, 61.1, 4120)]),
    span("respond", 61.25, 61.7),
  ],
};

function flatten(root: Node, startMs: number): ObsObservation[] {
  const rows: ObsObservation[] = [];
  let counter = 0;
  const visit = (node: Node, parent: string | null, depth: number) => {
    counter += 1;
    const id = `obs_${counter.toString().padStart(3, "0")}`;
    const children = [...(node.children ?? [])].sort((a, b) => a.from - b.from);
    rows.push({
      id,
      parent_id: parent,
      name: node.name,
      type: node.type,
      kind: node.kind,
      depth,
      start: iso(startMs + node.from * 1000),
      end: iso(startMs + node.to * 1000),
      latency_ms: Math.round((node.to - node.from) * 1000),
      model: node.kind === "llm" ? MODEL : null,
      tokens: node.tokens ?? children.reduce((sum, c) => sum + subtreeTokens(c), 0),
      level: node.level ?? "DEFAULT",
      status_message: node.status ?? null,
      failed: node.failed ?? false,
      metadata: node.metadata ?? {},
    });
    for (const child of children) visit(child, id, depth + 1);
  };
  visit(root, null, 0);
  return rows;
}

function subtreeTokens(node: Node): number {
  return (node.tokens ?? 0) + (node.children ?? []).reduce((sum, c) => sum + subtreeTokens(c), 0);
}

function detailFor(item: ObsTraceItem): ObservabilityTraceDetail {
  const startMs = Date.parse(item.timestamp ?? new Date().toISOString());
  const isFeatured = item.question === QUESTIONS[0].q;
  const tree = isFeatured ? DETAIL_TREE : smallTree(item);
  const observations = flatten(tree, startMs);
  const agents = item.tags;
  const scores: ObsTraceScore[] = agents.flatMap((agent) =>
    SCORE_NAMES.map((name) => ({
      name,
      value: 1,
      passed: true,
      comment: null,
      agent,
      timestamp: iso(startMs + (tree.to - 2) * 1000),
    })),
  );
  if (item.status === "partial" && scores.length) {
    const evidence = scores.find((s) => s.name === "eval_evidence");
    if (evidence) {
      evidence.value = 0;
      evidence.passed = false;
      evidence.comment = "status is ok but the result carries no evidence";
    }
  }
  const a2a: ObsA2AMessage[] = isFeatured
    ? [
        {
          id: "msg_7c1e0b2a9d43f610",
          sender: "tech",
          recipient: "hr",
          type: "peer_request",
          hop_count: 1,
          chain: ["tech"],
          refused: false,
          reason: null,
          content: "Who is allocated to project 7 (ledger-sync), and does anyone have leave overlapping the next four weeks?",
          created_at: iso(startMs + 12_000),
        },
        {
          id: "msg_2f9a61c04be8d735",
          sender: "hr",
          recipient: "tech",
          type: "peer_request",
          hop_count: 2,
          chain: ["tech", "hr"],
          refused: true,
          reason: "cycle detected: 'tech' is already in the chain tech -> hr",
          content: "When did the last commit land on ledger-sync?",
          created_at: iso(startMs + 16_400),
        },
        {
          id: "msg_b3d07e5c1a2f8894",
          sender: "hr",
          recipient: "tech",
          type: "peer_response",
          hop_count: 1,
          chain: ["tech", "hr"],
          refused: false,
          reason: null,
          content: "Three people are allocated (lead at 120%); the lead is on leave for 9 working days from 14 Oct.",
          created_at: iso(startMs + 30_000),
        },
      ]
    : [];
  return {
    enabled: true,
    reason: null,
    host: HOST,
    trace: {
      id: item.id,
      name: item.name,
      question: item.question,
      timestamp: item.timestamp,
      latency_ms: isFeatured ? Math.round(tree.to * 1000) : item.latency_ms,
      tokens: observations[0].tokens,
      cost: item.cost,
      agents: item.agents,
      tags: item.tags,
      session_id: item.session_id,
      status: item.status,
      url: item.url,
    },
    observations,
    scores,
    a2a,
  };
}

function smallTree(item: ObsTraceItem): Node {
  const total = (item.latency_ms ?? 30_000) / 1000;
  const runEnd = total * 0.7;
  const runs: Node[] = item.tags.map((agent, i) => {
    const end = runEnd - i * 2.5;
    return span("run_agent", 3.2, end, [
      {
        name: `agent:${agent}`,
        kind: "agent",
        type: "AGENT",
        from: 3.3,
        to: end - 0.1,
        failed: item.status === "partial" && agent === "finance",
        level: item.status === "error" && i === 0 ? "ERROR" : "DEFAULT",
        status: item.status === "error" && i === 0 ? "ResourceExhausted: 429 quota exceeded after 4 retries" : undefined,
        metadata: { agent, mode: "task", subtask_id: `t${i + 1}`, hop_count: 0, chain: [] },
        children: [gen(3.4, 7.5, 1800), tool("lookup", 7.6, 8.4), gen(8.5, end - 0.3, 2300)],
      },
    ]);
  });
  return {
    name: "stakeholder_request",
    kind: "span",
    type: "AGENT",
    from: 0,
    to: total,
    children: [
      span("intake", 0.02, 0.2),
      span("plan", 0.21, 3.1, [gen(0.3, 3.0, 1600)]),
      ...runs,
      span("synthesise", runEnd + 0.1, total - 0.4, [gen(runEnd + 0.2, total - 0.5, 3000)]),
      span("respond", total - 0.35, total - 0.05),
    ],
  };
}

// ---------------------------------------------------------------------------

const NOW = Date.now();
const TRACES = generate(NOW);

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

const DISABLED_REASON =
  "Langfuse keys are not set. Add LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY (and LANGFUSE_HOST if not using cloud.langfuse.com) to .env, then restart the backend.";

async function gate(signal?: AbortSignal, delay = 700): Promise<Scenario> {
  const mode = scenario();
  await sleep(mode === "slow" ? 60_000 : delay, signal);
  if (mode === "error") throw new Error("502 Bad Gateway: the backend did not answer on :8000");
  return mode;
}

function emptySummary(reason: string | null, enabled: boolean): ObservabilitySummary {
  return {
    enabled,
    reason,
    host: HOST,
    window: null,
    supervisor: "ceo",
    latency_target_ms: 45_000,
    traces: 0,
    avg_latency_ms: null,
    p95_latency_ms: null,
    total_tokens: 0,
    total_cost: 0,
    llm_calls: 0,
    tool_calls: 0,
    peer_calls: 0,
    refusals: 0,
    error_rate: 0,
    success_rate: null,
    per_agent: [],
    scores: [],
    edges: [],
    timeseries: [],
  };
}

export const mockObservability: ObservabilityClient = {
  mode: "mock",
  async getSummary(days, signal) {
    const mode = await gate(signal);
    if (mode === "disabled") return emptySummary(DISABLED_REASON, false);
    if (mode === "empty") return summarise([], Date.now(), days);
    return summarise(TRACES, NOW, days);
  },
  async getTraces(days, limit, signal): Promise<ObservabilityTraces> {
    const mode = await gate(signal, 800);
    if (mode === "disabled") return { enabled: false, reason: DISABLED_REASON, host: HOST, traces: [] };
    if (mode === "empty") return { enabled: true, reason: null, host: HOST, traces: [] };
    const traces = TRACES.map((t) => t.item)
      .filter((t) => NOW - Date.parse(t.timestamp ?? "") <= days * DAY)
      .slice(0, limit);
    return { enabled: true, reason: null, host: HOST, traces };
  },
  async getTrace(id, signal) {
    await sleep(450, signal);
    const found = TRACES.find((t) => t.item.id === id);
    if (!found) throw new Error(`Trace ${id} was not found in Langfuse.`);
    return detailFor(found.item);
  },
};
