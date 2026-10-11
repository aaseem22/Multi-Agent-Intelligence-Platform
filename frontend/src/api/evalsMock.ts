// Scripted evals data for mock mode (VITE_USE_MOCK=true). Deterministic: every trial is derived
// from a seeded generator, so reloading shows the same runs. One run is "in progress" and
// advances while the page is open; starting a run from the launcher creates another.

import type { Evidence } from "../types/contracts";
import type {
  CalibrationStats,
  Dataset,
  DimensionVerdict,
  EvalTask,
  ExpectedBehaviour,
  GraderKind,
  GraderResult,
  HumanLabel,
  HumanLabelRequest,
  JudgeVerdict,
  RunConfig,
  RunProgress,
  RunStatus,
  RunSummary,
  SelfEvalRecord,
  SelfEvalStats,
  Suite,
  TaskSummary,
  TrialResult,
} from "../types/evals";
import type { StreamEvent } from "../types/events";
import type { EvalsClient } from "./evals";
import { ApiError } from "./http";

const AGENT_MODEL = "gemini-2.5-flash-lite";
const CEO_MODEL = "gemini-2.5-flash";
const JUDGE_MODEL = "groq/llama-3.3-70b-versatile";
const LANGFUSE = "https://cloud.langfuse.com/project/demo/traces";
const OWNER = "demo-owner";

// ---------------------------------------------------------------------------
// Seeded randomness
// ---------------------------------------------------------------------------

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** A number in [0, 1) that is stable for the same key. */
function rand(key: string): number {
  let x = hash(key) || 1;
  x ^= x << 13;
  x ^= x >>> 17;
  x ^= x << 5;
  return ((x >>> 0) % 10_000) / 10_000;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
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

async function respond<T>(value: T, signal?: AbortSignal, delay = 280): Promise<T> {
  await sleep(delay, signal);
  return structuredClone(value);
}

const MINUTE = 60_000;
const iso = (ms: number) => new Date(ms).toISOString();

// ---------------------------------------------------------------------------
// Dataset
// ---------------------------------------------------------------------------

const GRADER_KIND: Record<string, GraderKind> = {
  plan_routing: "code",
  peer_collaboration: "code",
  required_facts: "code",
  forbidden_facts: "code",
  clarification: "code",
  evidence_cited: "code",
  reports_unanswered: "code",
  answer_quality: "model",
  reference_match: "model",
};

function expected(partial: Partial<ExpectedBehaviour>): ExpectedBehaviour {
  return {
    clarification: false,
    agents_required: [],
    agents_forbidden: [],
    max_agents: null,
    peer_messages: "any",
    required_facts: [],
    forbidden_facts: [],
    must_report_unanswered: false,
    reference_answer: "",
    ...partial,
  };
}

interface TaskSeed {
  id: string;
  suite: Suite;
  category: string;
  question: string;
  expected: Partial<ExpectedBehaviour>;
  graders: string[];
  tags?: string[];
  notes: string;
  /** Base pass probability per trial, before run quality. */
  p: number;
}

const SINGLE = ["plan_routing", "required_facts", "evidence_cited", "answer_quality"];
const CROSS = ["plan_routing", "peer_collaboration", "required_facts", "evidence_cited", "answer_quality", "reference_match"];

const SEEDS: TaskSeed[] = [
  {
    id: "fin-001",
    suite: "regression",
    category: "single-domain",
    question: "What is our spend versus budget on Atlas Portal this quarter?",
    expected: {
      agents_required: ["finance"],
      max_agents: 1,
      peer_messages: "forbidden",
      required_facts: [
        { description: "Names the over-budget project", any_of: ["{scenario.over_budget.project_name}"] },
        { description: "States the overrun percentage", any_of: ["131%", "31% over"] },
      ],
      reference_answer: "Atlas Portal has spent INR 72.1 lakh against a Q3 budget of INR 55 lakh, 131% of budget. Contractors make up 41% of actuals.",
    },
    graders: SINGLE,
    tags: ["finance", "budget"],
    notes: "Guards the planted over-budget scenario. Finance alone owns budgets, so no other agent should be planned.",
    p: 0.97,
  },
  {
    id: "fin-002",
    suite: "regression",
    category: "single-domain",
    question: "Which three projects have the largest budget overruns in 2026-Q3?",
    expected: {
      agents_required: ["finance"],
      max_agents: 1,
      required_facts: [{ description: "Lists Atlas Portal first", any_of: ["Atlas Portal"] }],
      reference_answer: "Atlas Portal (131%), Forge CLI (114%) and Pulse Metrics (108%) have the largest Q3 overruns.",
    },
    graders: SINGLE,
    tags: ["finance"],
    notes: "Exercises top_overruns with ranking.",
    p: 0.93,
  },
  {
    id: "fin-003",
    suite: "capability",
    category: "single-domain",
    question: "Which department's people cost grew most last quarter?",
    expected: {
      agents_required: ["finance"],
      required_facts: [{ description: "Names the department with the largest growth", any_of: ["Data", "Data department"] }],
      reference_answer: "The Data department's people cost grew 9.4% quarter on quarter, the largest of the four departments, driven by two new hires.",
    },
    graders: [...SINGLE, "reference_match"],
    tags: ["finance", "payroll"],
    notes: "Payroll is owned by Finance, not HR. HR may be asked for headcount as a peer.",
    p: 0.7,
  },
  {
    id: "fin-004",
    suite: "regression",
    category: "single-domain",
    question: "Break down Ledger Sync expenses by category for July to September.",
    expected: {
      agents_required: ["finance"],
      max_agents: 1,
      reference_answer: "Ledger Sync Q3 expenses: salaries INR 23.7 lakh, cloud INR 6.2 lakh, tooling INR 2.9 lakh, travel INR 1.6 lakh.",
    },
    graders: SINGLE,
    notes: "Checks date-range handling in expenses_by_category.",
    p: 0.95,
  },
  {
    id: "hr-001",
    suite: "regression",
    category: "single-domain",
    question: "Who is allocated above 100% right now?",
    expected: {
      agents_required: ["hr"],
      max_agents: 1,
      peer_messages: "forbidden",
      required_facts: [{ description: "Names the over-allocated lead", any_of: ["{scenario.understaffed.lead_name}", "Priya Nair"] }],
      reference_answer: "Priya Nair is allocated at 140% across Ledger Sync, Atlas Portal and Pulse Metrics. Nobody else is above 100%.",
    },
    graders: SINGLE,
    tags: ["hr"],
    notes: "Planted understaffed scenario: the lead is over-allocated.",
    p: 0.96,
  },
  {
    id: "hr-002",
    suite: "regression",
    category: "single-domain",
    question: "How many open positions does Engineering have?",
    expected: {
      agents_required: ["hr"],
      max_agents: 1,
      reference_answer: "Engineering has 3 open positions: two backend engineers and one SRE.",
    },
    graders: SINGLE,
    notes: "Simple lookup; should never fail.",
    p: 0.98,
  },
  {
    id: "hr-003",
    suite: "capability",
    category: "single-domain",
    question: "Does anyone on Ledger Sync have leave overlapping with the August release window?",
    expected: {
      agents_required: ["hr"],
      required_facts: [{ description: "States the overlap dates", any_of: ["4 to 22 August", "4-22 Aug", "2026-08-04"] }],
      reference_answer: "Arjun Mehta and Kavya Rao were both on leave from 4 to 22 August, overlapping the release window.",
    },
    graders: [...SINGLE, "reference_match"],
    notes: "Leave overlap needs date arithmetic the agent sometimes gets wrong.",
    p: 0.66,
  },
  {
    id: "hr-004",
    suite: "regression",
    category: "single-domain",
    question: "What is the headcount by department as of today?",
    expected: { agents_required: ["hr"], max_agents: 1, reference_answer: "Engineering 14, Product 9, Data 10, Operations 7: 40 people in total." },
    graders: SINGLE,
    notes: "Aggregate query, regression guard for headcount_by_department.",
    p: 0.97,
  },
  {
    id: "tech-001",
    suite: "regression",
    category: "single-domain",
    question: "Which repositories have had no push in the last 60 days?",
    expected: {
      agents_required: ["tech"],
      max_agents: 1,
      required_facts: [{ description: "Names the stale repo", any_of: ["{scenario.stale_repo.repo_full_name}", "ledger-sync"] }],
      reference_answer: `${OWNER}/ledger-sync has had no push since 12 July (91 days).`,
    },
    graders: SINGLE,
    tags: ["tech", "github"],
    notes: "Planted stale-repo scenario, read from cached GitHub fixtures.",
    p: 0.95,
  },
  {
    id: "tech-002",
    suite: "regression",
    category: "single-domain",
    question: "Which repo has the most open issues?",
    expected: { agents_required: ["tech"], max_agents: 1, reference_answer: `${OWNER}/atlas-portal has 23 open issues, 9 labelled blocked-on-vendor.` },
    graders: SINGLE,
    notes: "Ranking across repos.",
    p: 0.94,
  },
  {
    id: "tech-003",
    suite: "capability",
    category: "single-domain",
    question: "Which projects are past their planned end date but still in progress?",
    expected: {
      agents_required: ["tech"],
      required_facts: [
        { description: "Ledger Sync is late", any_of: ["Ledger Sync"] },
        { description: "Atlas Portal is late", any_of: ["Atlas Portal"] },
      ],
      reference_answer: "Ledger Sync (34 days late) and Atlas Portal (12 days late) are past their planned end date and still in progress.",
    },
    graders: [...SINGLE, "reference_match"],
    notes: "Delivery-status reasoning over planned_end vs status.",
    p: 0.78,
  },
  {
    id: "x-001",
    suite: "capability",
    category: "cross-domain",
    question: "Which technology projects are behind schedule, and is the cause people or budget?",
    expected: {
      agents_required: ["tech", "hr", "finance"],
      peer_messages: "required",
      required_facts: [
        { description: "Ledger Sync is a people problem", any_of: ["over-allocated", "overlapping leave"] },
        { description: "Atlas Portal is a budget problem", any_of: ["131%", "over budget"] },
      ],
      reference_answer:
        "Ledger Sync is late because of people: its lead is at 140% allocation and two engineers had overlapping leave, while it is within budget. Atlas Portal is late because of budget: staffing is at plan but spend is 131% of budget.",
    },
    graders: CROSS,
    tags: ["headline", "a2a"],
    notes: "The headline question from the design document. Needs all three departments and a Tech to HR peer request.",
    p: 0.62,
  },
  {
    id: "x-002",
    suite: "capability",
    category: "cross-domain",
    question: "Is the project with both budget and staffing problems getting worse?",
    expected: {
      agents_required: ["finance", "hr"],
      required_facts: [{ description: "Names the both-problems project", any_of: ["{scenario.both.project_name}", "Pulse Metrics"] }],
      reference_answer: "Pulse Metrics is 108% over budget and its two engineers are both above 110% allocation; spend rose 6% month on month, so it is getting worse.",
    },
    graders: CROSS,
    notes: "Planted 'both problems' scenario; requires trend reasoning.",
    p: 0.48,
  },
  {
    id: "x-003",
    suite: "capability",
    category: "cross-domain",
    question: "What does the over-allocation on Ledger Sync cost us per month?",
    expected: {
      agents_required: ["hr", "finance"],
      required_facts: [{ description: "States the monthly cost", any_of: ["7.9 lakh", "790,000"] }],
      reference_answer: "The three Ledger Sync engineers cost INR 7.9 lakh per month; the lead's 40% over-allocation accounts for about INR 1.3 lakh of that.",
    },
    graders: CROSS,
    notes: "HR identifies the people, Finance prices them.",
    p: 0.58,
  },
  {
    id: "x-004",
    suite: "regression",
    category: "cross-domain",
    question: "Is our healthiest project on budget and fully staffed?",
    expected: {
      agents_required: ["finance", "hr"],
      required_facts: [{ description: "Names the healthy project", any_of: ["{scenario.healthy.project_name}", "Beacon Docs"] }],
      reference_answer: "Beacon Docs is at 88% of budget and fully staffed at plan with nobody over-allocated.",
    },
    graders: CROSS.filter((g) => g !== "peer_collaboration"),
    notes: "The planted healthy project; the answer must not invent problems.",
    p: 0.9,
  },
  {
    id: "a2a-001",
    suite: "capability",
    category: "a2a",
    question: "Who is working on the repo with the most open issues, and are they over-allocated?",
    expected: {
      agents_required: ["tech"],
      peer_messages: "required",
      required_facts: [{ description: "Names the people on atlas-portal", any_of: ["5 people", "five"] }],
      reference_answer: "Atlas Portal has the most open issues (23). Its 5 staff are all at or below 100% allocation, according to HR.",
    },
    graders: CROSS,
    tags: ["a2a"],
    notes: "Tech must ask HR as a peer instead of reading allocations.",
    p: 0.64,
  },
  {
    id: "a2a-002",
    suite: "capability",
    category: "a2a",
    question: "The stale repo: who owns it and are they on leave?",
    expected: {
      agents_required: ["tech"],
      peer_messages: "required",
      reference_answer: "ledger-sync is led by Priya Nair, who is not on leave; two of her engineers were on leave 4-22 August.",
    },
    graders: CROSS,
    notes: "Planned-dependency example from the spec: Tech finds the stalled repo and asks HR.",
    p: 0.6,
  },
  {
    id: "a2a-003",
    suite: "capability",
    category: "a2a",
    question: "For each over-allocated person, what repos have they committed to recently?",
    expected: {
      agents_required: ["hr"],
      peer_messages: "required",
      must_report_unanswered: true,
      reference_answer: "Only the account owner has a GitHub username. Commit history for other employees cannot be attributed; the answer should say so.",
    },
    graders: [...CROSS, "reports_unanswered"],
    notes: "Hop limit and unmapped usernames: the honest answer reports what could not be answered.",
    p: 0.4,
  },
  {
    id: "a2a-004",
    suite: "regression",
    category: "a2a",
    question: "Ask Finance what Tech's cloud spend was, then ask Tech whether usage justifies it.",
    expected: {
      agents_required: ["finance", "tech"],
      reference_answer: "Cloud spend across Engineering was INR 18.4 lakh in Q3; Tech reports repo activity on 7 of 9 projects that use it.",
    },
    graders: CROSS.filter((g) => g !== "peer_collaboration"),
    notes: "Guards the peer call limit (3 per agent) and cycle detection.",
    p: 0.88,
  },
  {
    id: "clr-001",
    suite: "regression",
    category: "clarification",
    question: "How are we doing?",
    expected: { clarification: true, agents_forbidden: ["finance", "hr", "tech"], max_agents: 0 },
    graders: ["clarification", "plan_routing"],
    notes: "Too vague to plan; the CEO must ask back and dispatch nobody.",
    p: 0.98,
  },
  {
    id: "clr-002",
    suite: "regression",
    category: "clarification",
    question: "Give me an update.",
    expected: { clarification: true, max_agents: 0 },
    graders: ["clarification", "plan_routing"],
    notes: "Second phrasing of a vague request.",
    p: 0.92,
  },
  {
    id: "clr-003",
    suite: "capability",
    category: "clarification",
    question: "Are the numbers OK?",
    expected: { clarification: true, max_agents: 0 },
    graders: ["clarification", "plan_routing", "answer_quality"],
    notes: "Ambiguous between budget and delivery; a good clarification offers both.",
    p: 0.72,
  },
  {
    id: "ref-001",
    suite: "regression",
    category: "refusal",
    question: "What is the salary of Priya Nair's manager at her previous employer?",
    expected: {
      must_report_unanswered: true,
      forbidden_facts: [{ description: "Invented salary figure", any_of: ["INR", "lakh"] }],
      reference_answer: "No agent owns data about previous employers; the answer must say this cannot be answered.",
    },
    graders: ["reports_unanswered", "forbidden_facts", "answer_quality"],
    notes: "Data no agent owns. The system must not invent an answer.",
    p: 0.9,
  },
  {
    id: "ref-002",
    suite: "regression",
    category: "refusal",
    question: "Open a pull request to fix the stale repo.",
    expected: {
      must_report_unanswered: true,
      reference_answer: "The system is read-only and cannot open pull requests; it can report the repo's activity instead.",
    },
    graders: ["reports_unanswered", "answer_quality"],
    notes: "Write actions are out of scope; GitHub access is GET only.",
    p: 0.94,
  },
  {
    id: "ref-003",
    suite: "capability",
    category: "refusal",
    question: "Who is the most productive engineer by commits?",
    expected: {
      must_report_unanswered: true,
      forbidden_facts: [{ description: "Invented GitHub usernames", any_of: ["@"] }],
      reference_answer: "Only one employee is mapped to a GitHub username, so commit counts cannot rank engineers.",
    },
    graders: ["reports_unanswered", "forbidden_facts", "answer_quality"],
    notes: "Tempts the agents to invent usernames.",
    p: 0.55,
  },
];

const DATASET: Dataset = {
  name: "golden",
  version: "1.2.0",
  description: "Hand-written tasks over the seeded fictional organisation, with ground truth from scenarios.json.",
  tasks: SEEDS.map(
    (seed): EvalTask => ({
      id: seed.id,
      suite: seed.suite,
      category: seed.category,
      question: seed.question,
      expected: expected(seed.expected),
      graders: seed.graders,
      tags: seed.tags ?? [],
      notes: seed.notes,
    }),
  ),
};

const SMOKE: Dataset = {
  name: "smoke",
  version: "0.3.0",
  description: "Four quick tasks for checking the harness end to end before a full run.",
  tasks: DATASET.tasks.filter((t) => ["fin-001", "hr-001", "tech-001", "clr-001"].includes(t.id)),
};

const DATASETS = [DATASET, SMOKE];
const SEED_BY_ID = new Map(SEEDS.map((seed) => [seed.id, seed]));

// ---------------------------------------------------------------------------
// Trials
// ---------------------------------------------------------------------------

const RUBRIC_DIMS: Record<string, string[]> = {
  answer_quality: ["correctness", "groundedness", "completeness"],
  reference_match: ["key_facts", "no_contradiction"],
};

const PASS_REASONING: Record<string, string> = {
  correctness: "The figures match the evidence the agents cited.",
  groundedness: "Every claim points to a database record, GitHub response or peer answer.",
  completeness: "Both parts of the question are answered.",
  key_facts: "The answer states the same key facts as the reference.",
  no_contradiction: "Nothing in the answer contradicts the reference.",
};

const FAIL_REASONING: Record<string, string> = {
  correctness: "States the cause as budget for Ledger Sync, but Finance's evidence shows it at 82% of budget.",
  groundedness: "One claim about leave dates has no evidence reference attached.",
  completeness: "Answers which projects are late but not whether the cause is people or budget.",
  key_facts: "Omits the overrun percentage the reference gives.",
  no_contradiction: "Says staffing is at plan, which contradicts the reference.",
};

interface RunPlan {
  run_id: string;
  config: RunConfig;
  quality: number;
  created: number;
  /** Trials completed so far, or null when the run has finished. */
  done: number | null;
  status: RunStatus;
  startedLive?: number;
}

function judgeVerdict(grader: string, passed: boolean, key: string, withUnknown: boolean): JudgeVerdict {
  const dims = RUBRIC_DIMS[grader] ?? ["overall"];
  const failing = passed ? -1 : Math.floor(rand(`${key}:dim`) * dims.length);
  const dimensions: DimensionVerdict[] = dims.map((dimension, i) => {
    if (withUnknown && i === dims.length - 1) {
      return {
        dimension,
        verdict: "unknown",
        score: 0.5,
        reasoning: "The reference answer does not cover vendor-level spend, so I cannot judge this part either way.",
      };
    }
    const fail = i === failing;
    const score = fail ? 0.2 + rand(`${key}:${i}`) * 0.25 : 0.78 + rand(`${key}:${i}`) * 0.2;
    return {
      dimension,
      verdict: fail ? "fail" : "pass",
      score: Number(score.toFixed(2)),
      reasoning: fail ? FAIL_REASONING[dimension] ?? "Does not meet the rubric." : PASS_REASONING[dimension] ?? "Meets the rubric.",
    };
  });
  const known = dimensions.filter((d) => d.verdict !== "unknown");
  const score = known.reduce((sum, d) => sum + d.score, 0) / Math.max(known.length, 1);
  return {
    rubric: grader,
    passed,
    score: Number(score.toFixed(2)),
    dimensions,
    model: JUDGE_MODEL,
    feedback: passed
      ? "Well grounded. Consider stating the period explicitly."
      : `Revise the ${dimensions.find((d) => d.verdict === "fail")?.dimension ?? "answer"}: ${dimensions.find((d) => d.verdict === "fail")?.reasoning ?? ""}`,
    error: null,
  };
}

function failingGrader(seed: TaskSeed, key: string): string {
  const preferred: Record<string, string[]> = {
    "cross-domain": ["required_facts", "answer_quality", "reference_match"],
    a2a: ["peer_collaboration", "answer_quality", "reports_unanswered"],
    clarification: ["clarification", "answer_quality"],
    refusal: ["forbidden_facts", "reports_unanswered", "answer_quality"],
    "single-domain": ["required_facts", "answer_quality", "reference_match"],
  };
  const options = (preferred[seed.category] ?? seed.graders).filter((g) => seed.graders.includes(g));
  const list = options.length > 0 ? options : seed.graders;
  return list[Math.floor(rand(`${key}:fg`) * list.length)];
}

function codeReasons(grader: string, passed: boolean, seed: TaskSeed): string[] {
  const exp = expected(seed.expected);
  switch (grader) {
    case "plan_routing":
      return passed
        ? [`Planned ${exp.agents_required.join(", ") || "no agents"} as required.`]
        : [`Planned ${["finance", "hr", "tech"].join(", ")}; max_agents is ${exp.max_agents ?? "unset"}.`];
    case "peer_collaboration":
      if (passed && exp.peer_messages !== "required") return ["Peer requests were optional; none broke the guards."];
      return passed ? ["At least one peer request was made and answered."] : ["Expected a peer request; none was sent. Tech read staffing from its own tools."];
    case "required_facts":
      return exp.required_facts.map((fact, i) =>
        passed || i > 0 ? `Found: ${fact.description}.` : `Missing: ${fact.description} (any of ${fact.any_of.map((a) => `"${a}"`).join(", ")}).`,
      );
    case "forbidden_facts":
      return passed ? ["No forbidden facts appear."] : [`Forbidden fact present: ${exp.forbidden_facts[0]?.description ?? "invented detail"}.`];
    case "clarification":
      return passed ? ["The CEO asked a clarifying question and dispatched no agents."] : ["The CEO dispatched Finance instead of asking back."];
    case "evidence_cited":
      return passed ? ["Every claim cites evidence present in the agent results."] : ["Claim 2 cites a reference not found in any result."];
    case "reports_unanswered":
      return passed ? ["The answer says plainly what could not be answered."] : ["The answer presents a guess instead of reporting the gap."];
    default:
      return [];
  }
}

function trialFor(plan: RunPlan, seed: TaskSeed, index: number, withTranscript: boolean): TrialResult {
  const key = `${plan.run_id}:${seed.id}:${index}`;
  const roll = rand(key);
  const p = Math.min(0.99, seed.p * plan.quality);
  const errored = rand(`${key}:err`) < 0.025;
  let passed = !errored && roll < p;
  // Fixed showcase cases so the mock always exhibits the interesting states.
  const showcaseJudgeFail = seed.id === "x-001" && index === 1 && plan.run_id === "run_1009";
  const showcaseUnknown = seed.id === "fin-003" && plan.run_id === "run_1009" && index === 0;
  const showcaseRetry = seed.id === "x-003" && index === 0;
  if (showcaseJudgeFail) passed = false;
  if (showcaseUnknown || showcaseRetry) passed = true;

  const failing = passed || errored ? null : showcaseJudgeFail ? "answer_quality" : failingGrader(seed, key);
  const graders: GraderResult[] = errored
    ? []
    : seed.graders.map((grader) => {
        const kind = GRADER_KIND[grader] ?? "code";
        const ok = grader !== failing;
        if (kind === "model") {
          const judge = judgeVerdict(grader, ok, `${key}:${grader}`, showcaseUnknown && grader === "reference_match");
          return {
            grader,
            kind,
            passed: ok,
            score: judge.score ?? 0,
            weight: grader === "answer_quality" ? 2 : 1,
            reasons: [judge.feedback],
            judge,
            details: {},
          };
        }
        return { grader, kind, passed: ok, score: ok ? 1 : grader === "required_facts" ? 0.5 : 0, weight: 1, reasons: codeReasons(grader, ok, seed), judge: null, details: {} };
      });
  const totalWeight = graders.reduce((sum, g) => sum + g.weight, 0);
  const weighted = totalWeight ? graders.reduce((sum, g) => sum + g.score * g.weight, 0) / totalWeight : 0;
  // A failed required grader caps the trial score, as the harness threshold would.
  const score = passed ? weighted : Math.min(weighted * 0.7, 0.62);
  const exp = expected(seed.expected);
  const recoveries = showcaseRetry ? 1 : rand(`${key}:rec`) < 0.12 ? 1 : 0;
  const peerRequests = exp.peer_messages === "required" && failing !== "peer_collaboration" ? 1 + Math.floor(rand(`${key}:peer`) * 2) : 0;
  const refusals = seed.category === "a2a" && rand(`${key}:ref`) < 0.35 ? 1 : 0;
  const started = plan.created + 2 * MINUTE + (SEEDS.indexOf(seed) * plan.config.trials + index) * 70_000;
  const duration = 38_000 + Math.floor(rand(`${key}:dur`) * 52_000) + recoveries * 20_000;
  const clarification = exp.clarification && failing !== "clarification" ? "Could you narrow that down? For example delivery status, budget versus actual, or staffing." : null;
  const finalAnswer = errored || clarification ? null : passed ? exp.reference_answer : `${exp.reference_answer.split(". ")[0]}. The cause could not be confirmed from the available records.`;
  const agentsPlanned = exp.clarification ? (failing === "clarification" ? ["finance"] : []) : exp.agents_required.length ? exp.agents_required : ["finance"];
  const trial: TrialResult = {
    trial_id: `${seed.id}-t${index}`,
    run_id: plan.run_id,
    task_id: seed.id,
    index,
    status: errored ? "error" : passed ? "passed" : "failed",
    score: Number(score.toFixed(3)),
    passed,
    graders,
    question: seed.question,
    final_answer: finalAnswer,
    clarification,
    agents_planned: agentsPlanned,
    peer_requests: peerRequests,
    refusals,
    recoveries,
    duration_ms: duration,
    llm_calls: errored ? 6 : 9 + agentsPlanned.length * 3 + peerRequests * 2 + recoveries * 3,
    error: errored ? "Gemini rate limit: retries exhausted after 4 attempts (429 RESOURCE_EXHAUSTED)." : null,
    trace_url: errored ? null : `${LANGFUSE}/${plan.run_id}-${seed.id}-${index}`,
    transcript: [],
    started_at: iso(started),
    finished_at: iso(started + duration),
  };
  if (withTranscript) trial.transcript = transcriptFor(trial, seed, started, failing) as unknown as Record<string, unknown>[];
  return trial;
}

// ---------------------------------------------------------------------------
// Transcripts: plausible stream events for one trial
// ---------------------------------------------------------------------------

const TOOLS: Record<string, [string, Record<string, unknown>][]> = {
  finance: [
    ["budget_vs_actual", { period: "2026-Q3" }],
    ["expenses_by_category", { project_id: 3, start: "2026-07-01", end: "2026-09-30" }],
  ],
  hr: [
    ["project_staffing", { project_id: 7 }],
    ["leave_overlap", { project_id: 7, start: "2026-07-01", end: "2026-08-31" }],
  ],
  tech: [
    ["list_projects", { status: "in_progress" }],
    ["repo_activity", { repo: `${OWNER}/ledger-sync`, since: "2026-07-01" }],
  ],
};

const EVIDENCE: Record<string, Evidence[]> = {
  finance: [{ source_type: "db", source_ref: "budgets:id=19", summary: "Atlas Portal Q3 budget INR 55 lakh; actual INR 72.1 lakh (131%).", data: { pct: 131 } }],
  hr: [{ source_type: "db", source_ref: "allocations:employee_id=12", summary: "Priya Nair is allocated 140% across three projects.", data: { total_pct: 140 } }],
  tech: [
    { source_type: "db", source_ref: "projects:id=7", summary: "Ledger Sync planned end 2026-08-24, still in progress.", data: null },
    { source_type: "github", source_ref: `github:repos/${OWNER}/ledger-sync/commits?since=2026-07-01`, summary: "No commits since 12 July.", data: { commits: 0 } },
  ],
};

function transcriptFor(trial: TrialResult, seed: TaskSeed, startMs: number, failing: string | null): StreamEvent[] {
  let t = startMs;
  const req = `req_${trial.trial_id}`;
  const base = (step = 900) => {
    t += step;
    return { request_id: req, conversation_id: `eval_${trial.run_id}`, timestamp: iso(t) };
  };
  const events: StreamEvent[] = [];
  if (trial.clarification) {
    events.push({ ...base(1800), type: "clarification", question: trial.clarification });
    return events;
  }
  const subtasks = trial.agents_planned.map((agent, i) => ({
    id: `st_${i + 1}`,
    assigned_to: agent,
    instruction: `${seed.question} Answer only from the ${agent} domain and cite record ids.`,
    depends_on: [],
  }));
  events.push({ ...base(2200), type: "plan", subtasks, rationale: `Routing by agent cards: ${trial.agents_planned.join(", ")} own the data this question needs.` });
  for (const st of subtasks) {
    events.push({
      ...base(150),
      type: "peer_message",
      refused: false,
      refusal_reason: null,
      message: {
        id: `msg_${st.id}`,
        request_id: req,
        trace_id: null,
        sender: "ceo",
        recipient: st.assigned_to,
        type: "task",
        content: st.instruction,
        payload: { subtask_id: st.id },
        hop_count: 0,
        chain: ["ceo"],
        created_at: iso(t),
      },
    });
    events.push({ ...base(120), type: "agent_started", agent: st.assigned_to, subtask_id: st.id, mode: "task", instruction: st.instruction });
  }
  if (trial.error) {
    events.push({ ...base(4000), type: "error", message: trial.error, agent: subtasks[0]?.assigned_to ?? null });
    return events;
  }
  for (const st of subtasks) {
    for (const [tool, args] of TOOLS[st.assigned_to] ?? []) {
      events.push({ ...base(1300), type: "tool_call", agent: st.assigned_to, subtask_id: st.id, tool, args });
    }
  }
  const lead = subtasks[0];
  if (lead && trial.peer_requests > 0) {
    const target = lead.assigned_to === "hr" ? "finance" : "hr";
    const question = target === "hr" ? "Who is allocated to Ledger Sync, and did anyone have overlapping leave in August?" : "What is the monthly payroll cost for employees 12, 18 and 23?";
    const msg = (type: "peer_request" | "peer_response", sender: string, recipient: string, content: string, extra: Record<string, unknown> = {}) => ({
      id: `msg_${type}_${sender}`,
      request_id: req,
      trace_id: null,
      sender,
      recipient,
      type,
      content,
      payload: extra,
      hop_count: 1,
      chain: ["ceo", lead.assigned_to],
      created_at: iso(t),
    });
    events.push({ ...base(800), type: "peer_message", refused: false, refusal_reason: null, message: msg("peer_request", lead.assigned_to, target, question) });
    events.push({ ...base(200), type: "agent_started", agent: target, subtask_id: lead.id, mode: "peer", instruction: question });
    const [peerTool, peerArgs] = (TOOLS[target] ?? [])[0];
    events.push({ ...base(1400), type: "tool_call", agent: target, subtask_id: lead.id, tool: peerTool, args: peerArgs });
    const peerAnswer = target === "hr" ? "Ledger Sync has 3 people; the lead is at 140% and two engineers had overlapping leave 4-22 Aug." : "Payroll for the three engineers is INR 7.9 lakh per month.";
    events.push({
      ...base(1800),
      type: "agent_result",
      mode: "peer",
      result: { agent: target, subtask_id: lead.id, status: "ok", answer: peerAnswer, evidence: EVIDENCE[target], peer_messages: [], error: null },
    });
    events.push({ ...base(100), type: "peer_message", refused: false, refusal_reason: null, message: msg("peer_response", target, lead.assigned_to, peerAnswer) });
  }
  if (lead && trial.refusals > 0) {
    const reason = "Hop limit reached: hop_count 3 would exceed MAX_PEER_HOPS=2.";
    events.push({
      ...base(700),
      type: "peer_message",
      refused: true,
      refusal_reason: reason,
      message: {
        id: "msg_refused",
        request_id: req,
        trace_id: null,
        sender: "finance",
        recipient: "tech",
        type: "peer_request",
        content: "Which of employees 12, 18 and 23 authored commits this quarter?",
        payload: { refused: true, reason },
        hop_count: 3,
        chain: ["ceo", lead.assigned_to, "hr", "finance"],
        created_at: iso(t),
      },
    });
  }
  const evalsFor = (agent: string, subtaskId: string, attempt: number, judgePass: boolean): StreamEvent[] => {
    const judge = judgeVerdict("answer_quality", judgePass, `${trial.trial_id}:${agent}:${attempt}`, false);
    return (["self", "independent", "evidence"] as const).map((stage) => ({
      ...base(stage === "independent" ? 2400 : 200),
      type: "eval_result" as const,
      agent,
      subtask_id: subtaskId,
      attempt,
      judge: stage === "independent" ? judge : null,
      result: {
        passed: stage === "independent" ? judgePass : true,
        stage,
        reasons:
          stage === "self"
            ? ["Status is ok and the answer cites 2 evidence records."]
            : stage === "evidence"
              ? ["Every evidence reference resolves to a record or API response."]
              : judge.dimensions.filter((d) => d.verdict !== "pass").map((d) => `${d.dimension}: ${d.reasoning}`),
        score: stage === "independent" ? judge.score : null,
      },
    }));
  };
  subtasks.forEach((st, i) => {
    const agent = st.assigned_to;
    const result = (answer: string) => ({
      ...base(2000),
      type: "agent_result" as const,
      mode: "task" as const,
      result: { agent, subtask_id: st.id, status: "ok" as const, answer, evidence: EVIDENCE[agent] ?? [], peer_messages: [], error: null },
    });
    const retryHere = trial.recoveries > 0 && i === 0;
    events.push(result(retryHere ? "Ledger Sync is late because of budget." : `${agent === "tech" ? "Ledger Sync is 34 days late with no push since 12 July." : agent === "hr" ? "The Ledger Sync lead is at 140% allocation; two engineers had overlapping leave." : "Atlas Portal is at 131% of its Q3 budget."}`));
    if (retryHere) {
      events.push(...evalsFor(agent, st.id, 1, false));
      events.push({
        ...base(300),
        type: "recovery",
        agent,
        subtask_id: st.id,
        action: "retry",
        attempt: 1,
        reasons: ["independent: correctness below threshold (0.38 < 0.6)"],
        feedback: "Your answer blames budget, but your own evidence shows Ledger Sync at 82% of budget. Re-check the cause against the staffing data.",
      });
      events.push({ ...base(200), type: "agent_started", agent, subtask_id: st.id, mode: "task", instruction: `${st.instruction} Reviewer feedback: re-check the cause against the staffing data.` });
      events.push({ ...base(1300), type: "tool_call", agent, subtask_id: st.id, tool: (TOOLS[agent] ?? [["lookup", {}]])[0][0], args: (TOOLS[agent] ?? [["lookup", {}]])[0][1] });
      events.push(result("Ledger Sync is within budget (82%); the delay follows the lead's over-allocation and overlapping leave."));
      events.push(...evalsFor(agent, st.id, 2, true));
    } else {
      events.push(...evalsFor(agent, st.id, 1, !(failing === "answer_quality" && i === 0)));
    }
  });
  events.push({
    ...base(3500),
    type: "final",
    answer: {
      answer: trial.final_answer ?? "",
      claims: subtasks.map((st) => ({ text: `${st.assigned_to} finding supported by its records.`, evidence_refs: (EVIDENCE[st.assigned_to] ?? []).map((e) => e.source_ref), agents: [st.assigned_to] })),
      unanswered: trial.passed ? [] : ["Part of the question could not be confirmed from the available records."],
    },
    results: [],
    trace_url: trial.trace_url,
  });
  return events;
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

const LOADED = Date.now();
const DAY = 24 * 60 * MINUTE;
const LIVE_STEP_MS = 3500;

function tasksFor(config: RunConfig): TaskSeed[] {
  const dataset = DATASETS.find((d) => d.name === config.dataset) ?? DATASET;
  const ids = new Set(dataset.tasks.map((t) => t.id));
  return SEEDS.filter((s) => ids.has(s.id) && config.suites.includes(s.suite) && (config.task_ids.length === 0 || config.task_ids.includes(s.id)));
}

const allSuites: Suite[] = ["capability", "regression"];
const plans: RunPlan[] = [
  { run_id: "run_0922", config: { dataset: "golden", suites: allSuites, task_ids: [], trials: 1, judge_enabled: true, self_eval_recovery: "observe" }, quality: 0.86, created: LOADED - 19 * DAY, done: null, status: "completed" },
  { run_id: "run_0930", config: { dataset: "golden", suites: allSuites, task_ids: [], trials: 1, judge_enabled: true, self_eval_recovery: "retry" }, quality: 0.93, created: LOADED - 11 * DAY, done: null, status: "completed" },
  { run_id: "run_1003", config: { dataset: "golden", suites: allSuites, task_ids: [], trials: 3, judge_enabled: true, self_eval_recovery: "retry" }, quality: 0.97, created: LOADED - 8 * DAY, done: null, status: "completed" },
  { run_id: "run_1005", config: { dataset: "smoke", suites: allSuites, task_ids: [], trials: 1, judge_enabled: false, self_eval_recovery: "observe" }, quality: 1, created: LOADED - 6 * DAY, done: 2, status: "cancelled" },
  { run_id: "run_1009", config: { dataset: "golden", suites: allSuites, task_ids: [], trials: 3, judge_enabled: true, self_eval_recovery: "retry" }, quality: 1.02, created: LOADED - 2 * DAY, done: null, status: "completed" },
  { run_id: "run_1011", config: { dataset: "golden", suites: ["regression"], task_ids: [], trials: 1, judge_enabled: true, self_eval_recovery: "retry" }, quality: 1.02, created: LOADED - 6 * MINUTE, done: 3, status: "running", startedLive: LOADED },
];

function liveDone(plan: RunPlan): number {
  const total = tasksFor(plan.config).length * plan.config.trials;
  if (plan.status !== "running" || plan.startedLive === undefined) return Math.min(plan.done ?? total, total);
  const done = Math.min(total, (plan.done ?? 0) + Math.floor((Date.now() - plan.startedLive) / LIVE_STEP_MS));
  if (done >= total) {
    plan.status = "completed";
    plan.done = null;
  }
  return done;
}

function trialsOf(plan: RunPlan, withTranscript = false): TrialResult[] {
  const done = liveDone(plan);
  const out: TrialResult[] = [];
  for (const seed of tasksFor(plan.config)) {
    for (let i = 0; i < plan.config.trials; i += 1) out.push(trialFor(plan, seed, i, withTranscript));
  }
  // Trials run task by task, so the first `done` are the finished ones.
  return out.slice(0, done);
}

function rate(items: boolean[]): number {
  return items.length ? items.filter(Boolean).length / items.length : 0;
}

function summarise(plan: RunPlan): RunSummary {
  const tasks = tasksFor(plan.config);
  const trials = trialsOf(plan);
  const k = plan.config.trials;
  const byTask = new Map<string, TrialResult[]>();
  for (const trial of trials) byTask.set(trial.task_id, [...(byTask.get(trial.task_id) ?? []), trial]);
  const taskSummaries: TaskSummary[] = [];
  for (const seed of tasks) {
    const list = byTask.get(seed.id);
    if (!list || list.length < k) continue;
    const graderRates: Record<string, number> = {};
    for (const grader of seed.graders) {
      const results = list.flatMap((t) => t.graders.filter((g) => g.grader === grader));
      if (results.length) graderRates[grader] = rate(results.map((g) => g.passed));
    }
    const passes = list.filter((t) => t.passed).length;
    taskSummaries.push({
      task_id: seed.id,
      suite: seed.suite,
      category: seed.category,
      question: seed.question,
      trials: list.length,
      passes,
      pass_at_k: passes > 0,
      pass_hat_k: passes === list.length,
      mean_score: list.reduce((sum, t) => sum + t.score, 0) / list.length,
      grader_pass_rates: graderRates,
    });
  }
  const group = (keyOf: (t: TrialResult) => string) => {
    const map: Record<string, boolean[]> = {};
    for (const trial of trials) (map[keyOf(trial)] ??= []).push(trial.passed);
    return Object.fromEntries(Object.entries(map).map(([key, list]) => [key, rate(list)]));
  };
  const graderRates: Record<string, boolean[]> = {};
  for (const trial of trials) for (const g of trial.graders) (graderRates[g.grader] ??= []).push(g.passed);
  const has = trials.length > 0;
  const finished = plan.status === "completed" || plan.status === "cancelled";
  return {
    run_id: plan.run_id,
    status: plan.status,
    config: plan.config,
    dataset_version: (DATASETS.find((d) => d.name === plan.config.dataset) ?? DATASET).version,
    agent_model: AGENT_MODEL,
    ceo_model: CEO_MODEL,
    judge_model: plan.config.judge_enabled ? JUDGE_MODEL : "-",
    created_at: iso(plan.created),
    started_at: iso(plan.created + MINUTE),
    finished_at: finished ? iso(plan.created + MINUTE + trials.length * 70_000) : null,
    tasks_total: tasks.length,
    trials_total: tasks.length * k,
    trials_done: trials.length,
    pass_rate: has ? rate(trials.map((t) => t.passed)) : null,
    pass_at_k: taskSummaries.length ? rate(taskSummaries.map((t) => t.pass_at_k)) : null,
    pass_hat_k: taskSummaries.length ? rate(taskSummaries.map((t) => t.pass_hat_k)) : null,
    mean_score: has ? trials.reduce((sum, t) => sum + t.score, 0) / trials.length : null,
    by_suite: group((t) => SEED_BY_ID.get(t.task_id)?.suite ?? "regression"),
    by_category: group((t) => SEED_BY_ID.get(t.task_id)?.category ?? "other"),
    grader_pass_rates: Object.fromEntries(Object.entries(graderRates).map(([key, list]) => [key, rate(list)])),
    tasks: taskSummaries,
    error: plan.status === "cancelled" ? "Cancelled from the evals page." : null,
  };
}

function findPlan(runId: string): RunPlan {
  const plan = plans.find((p) => p.run_id === runId);
  if (!plan) throw new ApiError(404, `Run ${runId} was not found.`);
  return plan;
}

// ---------------------------------------------------------------------------
// Labels and calibration
// ---------------------------------------------------------------------------

const labels = new Map<string, HumanLabel>(); // `${run}|${trial}|${grader}`

function seedLabels(): void {
  const plan = findPlan("run_1009");
  // The showcase judge failure (x-001, trial 2) is labelled first so it always carries a human verdict.
  const trials = trialsOf(plan).toSorted((a, b) => Number(b.trial_id === "x-001-t1") - Number(a.trial_id === "x-001-t1"));
  let n = 0;
  for (const trial of trials) {
    for (const g of trial.graders) {
      if (g.kind !== "model" || n >= 16) continue;
      if (rand(`${trial.trial_id}:${g.grader}:label`) > 0.42 && !(trial.task_id === "x-001" && trial.index === 1)) continue;
      n += 1;
      // Mostly agree; a few disagreements make the calibration numbers honest.
      const disagree = n === 4 || n === 9 || n === 13;
      labels.set(`${plan.run_id}|${trial.trial_id}|${g.grader}`, {
        trial_id: trial.trial_id,
        grader: g.grader,
        human_passed: disagree ? !g.passed : g.passed,
        note: disagree ? (g.passed ? "Judge missed that the leave dates are wrong." : "Answer is correct; the judge penalised wording.") : "",
        labelled_at: iso(plan.created + DAY + n * 7 * MINUTE),
      });
    }
  }
}
seedLabels();

function calibration(): CalibrationStats {
  let agree = 0;
  let falsePass = 0;
  let falseFail = 0;
  const byGrader: Record<string, [number, number]> = {};
  for (const [key, label] of labels) {
    const [runId] = key.split("|");
    const plan = plans.find((p) => p.run_id === runId);
    if (!plan) continue;
    const trial = trialsOf(plan).find((t) => t.trial_id === label.trial_id);
    const grader = trial?.graders.find((g) => g.grader === label.grader);
    if (!grader) continue;
    const same = grader.passed === label.human_passed;
    if (same) agree += 1;
    else if (grader.passed) falsePass += 1;
    else falseFail += 1;
    const entry = (byGrader[label.grader] ??= [0, 0]);
    entry[0] += same ? 1 : 0;
    entry[1] += 1;
  }
  const total = agree + falsePass + falseFail;
  return {
    labels: total,
    agreement: total ? agree / total : null,
    judge_false_pass: falsePass,
    judge_false_fail: falseFail,
    by_grader: Object.fromEntries(Object.entries(byGrader).map(([g, [a, n]]) => [g, a / n])),
  };
}

// ---------------------------------------------------------------------------
// Live self-evaluation
// ---------------------------------------------------------------------------

function selfEval(days: number): SelfEvalStats {
  const scale = days === 1 ? 1 : days === 7 ? 6 : 21;
  const now = Date.now();
  const at = (minutes: number) => iso(now - minutes * MINUTE);
  const judge = judgeVerdict("answer_quality", false, "selfeval-feed", false);
  const recent: SelfEvalRecord[] = [
    { request_id: "req_a91", conversation_id: "conv_seed_clarify", kind: "eval", agent: "finance", subtask_id: "st_fin", stage: "independent", action: null, passed: true, score: 0.88, attempt: 1, payload: { reasons: [], judge: judgeVerdict("answer_quality", true, "feed-ok", false) }, created_at: at(14) },
    { request_id: "req_a91", conversation_id: "conv_seed_clarify", kind: "eval", agent: "tech", subtask_id: "st_tech", stage: "independent", action: null, passed: false, score: 0.41, attempt: 1, payload: { reasons: ["completeness: Answers which projects are late but not why."], judge }, created_at: at(15) },
    { request_id: "req_a91", conversation_id: "conv_seed_clarify", kind: "recovery", agent: "tech", subtask_id: "st_tech", stage: null, action: "retry", passed: null, score: null, attempt: 1, payload: { reasons: ["independent: completeness below threshold"], feedback: "Say whether the cause is people or budget, citing HR's peer answer." }, created_at: at(15) },
    { request_id: "req_a91", conversation_id: "conv_seed_clarify", kind: "eval", agent: "tech", subtask_id: "st_tech", stage: "independent", action: null, passed: true, score: 0.83, attempt: 2, payload: { reasons: [] }, created_at: at(16) },
    { request_id: "req_a7c", conversation_id: null, kind: "eval", agent: "hr", subtask_id: "st_hr", stage: "evidence", action: null, passed: false, score: null, attempt: 1, payload: { reasons: ["Result has status ok but cites no evidence."] }, created_at: at(52) },
    { request_id: "req_a7c", conversation_id: null, kind: "recovery", agent: "hr", subtask_id: "st_hr", stage: null, action: "retry", passed: null, score: null, attempt: 1, payload: { reasons: ["evidence: no evidence cited"], feedback: "Cite the allocation record ids you used." }, created_at: at(52) },
    { request_id: "req_a7c", conversation_id: null, kind: "eval", agent: "hr", subtask_id: "st_hr", stage: "evidence", action: null, passed: true, score: null, attempt: 2, payload: { reasons: [] }, created_at: at(53) },
    { request_id: "req_a55", conversation_id: "conv_seed_clarify", kind: "eval", agent: "finance", subtask_id: "st_1", stage: "self", action: null, passed: false, score: null, attempt: 2, payload: { reasons: ["Status is failed: people_cost returned no rows for period 2026-13."] }, created_at: at(170) },
    { request_id: "req_a55", conversation_id: "conv_seed_clarify", kind: "recovery", agent: "finance", subtask_id: "st_1", stage: null, action: "give_up", passed: null, score: null, attempt: 2, payload: { reasons: ["self: still failing after 1 retry"], feedback: "" }, created_at: at(171) },
    { request_id: "req_a40", conversation_id: null, kind: "eval", agent: "tech", subtask_id: "st_1", stage: "independent", action: null, passed: null, score: null, attempt: 1, payload: { reasons: ["Judge error: Groq returned 503; the result was passed through unreviewed."] }, created_at: at(290) },
  ];
  return {
    window_days: days,
    evaluations: 42 * scale + 6,
    by_stage: { self: 0.96, independent: days === 1 ? 0.81 : 0.84, evidence: 0.93 },
    retries: 5 * scale,
    retry_success_rate: days === 30 ? 0.71 : 0.75,
    judge_errors: days === 1 ? 1 : 2 * scale,
    recent,
  };
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export const mockEvals: EvalsClient = {
  mode: "mock",
  getDatasets: (signal) => respond(DATASETS, signal),
  getRuns: (signal) => respond(plans.map(summarise).sort((a, b) => b.created_at.localeCompare(a.created_at)), signal),
  startRun: async (config) => {
    await sleep(400);
    for (const plan of plans) liveDone(plan);
    if (plans.some((p) => p.status === "running" || p.status === "queued")) {
      throw new ApiError(409, "Another eval run is already in progress.");
    }
    const plan: RunPlan = { run_id: `run_${Date.now().toString(36)}`, config, quality: 1.02, created: Date.now(), done: 0, status: "running", startedLive: Date.now() };
    plans.push(plan);
    return summarise(plan);
  },
  getRun: async (runId, signal) => respond(summarise(findPlan(runId)), signal),
  getProgress: async (runId, signal) => {
    const plan = findPlan(runId);
    const done = liveDone(plan);
    const tasks = tasksFor(plan.config);
    const current = tasks[Math.floor(done / plan.config.trials)];
    const running = plan.status === "running";
    const progress: RunProgress = {
      run_id: runId,
      status: plan.status,
      trials_total: tasks.length * plan.config.trials,
      trials_done: done,
      current_task: running ? current?.id ?? null : null,
      message: running && current ? `Trial ${(done % plan.config.trials) + 1} of ${current.id}: grading with ${plan.config.judge_enabled ? "code and model graders" : "code graders"}` : plan.status === "completed" ? "Run finished." : "Run stopped.",
      updated_at: iso(Date.now()),
    };
    return respond(progress, signal, 120);
  },
  cancelRun: async (runId) => {
    await sleep(250);
    const plan = findPlan(runId);
    if (plan.status === "running") {
      plan.done = liveDone(plan);
      plan.status = "cancelled";
    }
  },
  getTrials: async (runId, signal) => respond(trialsOf(findPlan(runId)), signal),
  getTrial: async (runId, trialId, signal) => {
    const trial = trialsOf(findPlan(runId), true).find((t) => t.trial_id === trialId);
    if (!trial) throw new ApiError(404, `Trial ${trialId} was not found.`);
    return respond(trial, signal);
  },
  getLabels: async (runId, signal) =>
    respond(
      [...labels.entries()].filter(([key]) => key.startsWith(`${runId}|`)).map(([, label]) => label),
      signal,
      150,
    ),
  putLabel: async (runId, request: HumanLabelRequest) => {
    await sleep(250);
    const label: HumanLabel = { trial_id: request.trial_id, grader: request.grader, human_passed: request.human_passed, note: request.note ?? "", labelled_at: iso(Date.now()) };
    labels.set(`${runId}|${request.trial_id}|${request.grader}`, label);
    return structuredClone(label);
  },
  getCalibration: (signal) => respond(calibration(), signal),
  getSelfEval: (days, signal) => respond(selfEval(days), signal),
};
