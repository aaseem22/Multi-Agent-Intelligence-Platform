# CLAUDE.md — Enterprise Multi-Agent Orchestration (Phase 1 build)

This file is the build specification for this repository. Read it fully before writing any code. It is based on the Solution Design Document "Self-Evaluating Multi-Agent Framework for Enterprise Workflow Orchestration" (M.Tech AI, NMIMS MPSTME). This build covers the agents and agent-to-agent (A2A) collaboration. The evaluation layer is stubbed only.

---

## 1. What we are building

A stakeholder asks a cross-department question in plain language, for example "Which technology projects are behind schedule, and is the cause people or budget?". A CEO agent interprets the question, splits it into subtasks and dispatches them to three department agents: Finance, HR and Tech. The department agents run in parallel against their own data. When one needs information another department owns, it asks that agent directly through an in-process A2A message instead of reading data it does not own. The CEO combines the results into one answer with evidence attached.

Agents in this build:

| Agent | Role | Owns |
|---|---|---|
| CEO | Supervisor. Interprets, plans, dispatches, synthesises, asks clarifying questions | No domain data. Reads agent cards and reference data only |
| Finance | Budgets, spend, cost of projects and people | `budgets`, `expenses`, `payroll` |
| HR | Staffing, allocations, leave, hiring | `employees`, `allocations`, `leave`, `open_positions` |
| Tech | Project delivery and repository activity | `projects` delivery fields, GitHub API (read-only) |

Shared reference data, readable by everyone: `departments`, and `projects` identity columns (`id`, `name`, `repo_full_name`).

### Hard design constraints

1. **Adding a fifth department must not change `app/core/`.** A new agent is a new folder under `app/agents/` plus one registration call. Nothing in core may name a specific department.
2. **Data ownership is enforced in code.** An agent's tools can only import its own repository modules plus reference data. There is a test that fails if this is violated.
3. **GitHub access is read-only.** The client exposes GET requests only. There is a test that fails if any non-GET method exists.
4. **Every agent output carries evidence.** Each claim must point to the records or API responses it came from, even though evaluation is stubbed in this build. The later evaluation layer depends on this.
5. **Peer delegation always terminates.** Hop limit, per-agent call limit and cycle detection are all mandatory (section 5).
6. **No writes to any external system.** No irreversible actions. No real organisational data.

### Out of scope for this build

Do not implement: self-evaluation, the independent judge, retry/replan logic beyond LLM transport retries, long-term memory, benchmarks, Supabase, deployment. Leave clean hook points for them as described in section 8.

---

## 2. Tech stack

| Area | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, managed with `uv` |
| Agents | LangGraph + LangChain |
| LLM | Google Gemini free tier via `langchain-google-genai` |
| Data | SQLite now (SQLAlchemy 2.x), Supabase/Postgres later |
| Conversation state | LangGraph SQLite checkpointer |
| Integration | GitHub REST API, read-only, user's own account |
| Observability | Langfuse Cloud (free tier) |
| Frontend | Vite + React + TypeScript + Tailwind |
| Quality | ruff, pytest, pytest-asyncio; tsc + eslint on the frontend |
| Runtime | Local only. No Docker, no deployment config |

**Library versions change quickly.** Before writing code against LangGraph, LangChain, langchain-google-genai or the Langfuse SDK, check the current docs (use the Context7 MCP server if available). Do not rely on memory for import paths. In particular, verify:
- the current prebuilt agent constructor (LangChain 1.x `create_agent` vs the older `langgraph.prebuilt.create_react_agent`);
- the `Send` API for parallel fan-out;
- the Langfuse LangChain callback handler import path for the current SDK major version;
- the current SQLite checkpointer package and class names.

Pin exact versions in `pyproject.toml` and `package.json` once chosen.

---

## 3. Repository layout

```
.
├── CLAUDE.md
├── .claude/agents/            # Claude Code subagent definitions used to build this repo
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py            # FastAPI app factory
│   │   ├── api/
│   │   │   ├── routes.py      # HTTP + SSE endpoints
│   │   │   └── schemas.py     # request/response models
│   │   ├── core/              # department-agnostic. Frozen after Phase 0
│   │   │   ├── config.py      # pydantic-settings, all env vars
│   │   │   ├── llm.py         # Gemini factory, shared rate limiter, retries
│   │   │   ├── contracts.py   # AgentCard, A2AMessage, Subtask, AgentResult, Evidence
│   │   │   ├── events.py      # SSE event schema streamed to the UI
│   │   │   ├── state.py       # LangGraph state definitions
│   │   │   ├── registry.py    # agent registry (register / get / list cards)
│   │   │   ├── base_agent.py  # DepartmentAgent base: builds the agent subgraph
│   │   │   ├── a2a.py         # ask_agent tool, hop/cycle/limit enforcement, message log
│   │   │   ├── eval_hooks.py  # STUBS: self_check, independent_eval, recovery router
│   │   │   ├── observability.py # Langfuse handler, trace/session helpers
│   │   │   └── orchestrator.py  # builds the top-level graph from registry + CEO
│   │   ├── data/
│   │   │   ├── db.py          # engine/session, DATABASE_URL driven
│   │   │   ├── models.py      # SQLAlchemy models
│   │   │   ├── repositories/
│   │   │   │   ├── reference.py
│   │   │   │   ├── finance.py
│   │   │   │   ├── hr.py
│   │   │   │   └── tech.py
│   │   │   └── seed/
│   │   │       ├── seed.py        # builds the fictional org around real repos
│   │   │       ├── fixtures_repos.json  # fallback repo list when no GitHub token
│   │   │       └── scenarios.json # planted ground-truth scenarios (written by seed)
│   │   ├── integrations/
│   │   │   └── github_client.py  # GET-only client with SQLite response cache
│   │   └── agents/
│   │       ├── ceo/        # planner, dispatcher, synthesiser, prompts
│   │       ├── finance/    # card.py, tools.py, prompts.py, agent.py
│   │       ├── hr/
│   │       └── tech/
│   └── tests/
│       ├── core/
│       ├── agents/
│       ├── test_data_ownership.py
│       ├── test_github_readonly.py
│       └── test_e2e_questions.py
└── frontend/
    ├── package.json
    ├── vite.config.ts        # proxy /api -> http://localhost:8000
    └── src/
        ├── types/            # mirrors backend contracts.py and events.py
        ├── api/              # fetch + SSE client
        ├── components/
        └── pages/
```

---

## 4. Core contracts (`app/core/contracts.py`)

Build these first. All are Pydantic v2 models. Once Phase 0 ends they are frozen. A subagent that needs a change must stop and report back rather than edit them.

```python
class AgentCard(BaseModel):
    name: str                      # "finance", "hr", "tech", "ceo"
    department: str
    description: str               # used by the CEO planner to route subtasks
    skills: list[Skill]            # Skill(name, description, example_questions)
    owned_data: list[str]          # table names / "github"
    accepts_peer_requests: bool = True

class Evidence(BaseModel):
    source_type: Literal["db", "github", "peer"]
    source_ref: str                # e.g. "expenses:id=42", "github:repo/pulls?state=open", "peer:hr:msg_id"
    summary: str                   # what this evidence shows, one line
    data: dict | None = None       # small raw excerpt

class Subtask(BaseModel):
    id: str
    assigned_to: str               # agent name
    instruction: str
    depends_on: list[str] = []

class A2AMessage(BaseModel):
    id: str
    request_id: str                # one stakeholder request
    trace_id: str | None
    sender: str
    recipient: str
    type: Literal["task", "peer_request", "peer_response", "result", "error", "clarification"]
    content: str
    payload: dict = {}
    hop_count: int = 0
    chain: list[str] = []          # agents visited, in order
    created_at: datetime

class AgentResult(BaseModel):
    agent: str
    subtask_id: str
    status: Literal["ok", "partial", "failed", "needs_clarification"]
    answer: str
    evidence: list[Evidence]
    peer_messages: list[str]       # A2AMessage ids this agent sent/received
    error: str | None = None

class EvalResult(BaseModel):       # used by the stubs in eval_hooks.py
    passed: bool
    stage: Literal["self", "independent", "evidence"]
    reasons: list[str] = []
    score: float | None = None
```

Every agent's final output must be parsed into `AgentResult` using structured output. If parsing fails, return `status="failed"` with the error. Never let a raw exception reach the CEO.

---

## 5. Agent-to-agent collaboration (in-process)

All agents live in one Python process. A2A is message passing between LangGraph subgraphs, not HTTP.

### Mechanism

Each department agent is a compiled LangGraph subgraph built by `DepartmentAgent` in `base_agent.py`. It is a tool-calling agent that owns its own domain tools, and it also gets one extra tool from `core/a2a.py`:

```
ask_agent(target: str, question: str) -> str
```

When called, `ask_agent`:
1. builds an `A2AMessage(type="peer_request")` with `hop_count = current + 1` and `chain = current_chain + [sender]`;
2. applies the guards below; if a guard trips, it returns a refusal string to the calling agent (it does not raise), so the agent can continue with what it has;
3. invokes the target agent's subgraph in **peer mode** with that message;
4. logs the request and the `peer_response` to the message log (SQLite table `a2a_messages`) and emits an SSE `peer_message` event;
5. returns the peer's answer, and its evidence summarised, to the caller. The caller must cite it as `Evidence(source_type="peer")`.

**Peer mode.** The target answers only from its own domain. It may call `ask_agent` itself only if the hop limit still allows it. It returns an `AgentResult`.

### Guards (all mandatory, all configurable via env)

| Guard | Default | Behaviour |
|---|---|---|
| `MAX_PEER_HOPS` | 2 | Refuse if `hop_count` would exceed it |
| `MAX_PEER_CALLS_PER_AGENT` | 3 | Per agent, per stakeholder request |
| Cycle detection | on | Refuse if `target` is already in `chain` |
| Self-call | refused | An agent cannot ask itself |
| Unknown target | refused | Target must exist in the registry and have `accepts_peer_requests=True` |
| CEO as target | refused | Department agents cannot delegate upward. They report `needs_clarification` instead |
| LangGraph recursion limit | 40 | Set on every invoke |

The list of valid peers comes from the registry at runtime. The `ask_agent` tool description must include each peer's card description, generated from the registry, so agents know who owns what. Nothing in the tool may hardcode department names.

---

## 6. CEO agent and top-level graph

`core/orchestrator.py` builds the top-level graph from the registry. The CEO nodes are defined in `agents/ceo/`.

```
START
  -> intake          # normalise the question, load conversation context from checkpointer
  -> plan            # structured output: either a list[Subtask] or a clarification question
  -> [clarify?] ---- if clarification needed -> respond(type=clarification) -> END
  -> dispatch        # Send API: one Send per subtask with no pending depends_on, in parallel
  -> run_agent       # invokes the department subgraph; returns AgentResult
  -> eval_gate       # calls eval_hooks.independent_eval (STUB: always passes); routes via recovery_router (STUB: only "pass")
  -> collect         # reducer merges AgentResults; dispatches dependent subtasks if any
  -> synthesise      # CEO combines results into one answer; every claim cites evidence from results
  -> respond -> END
```

Planner rules for the CEO prompt:
- Route using agent cards only. Never answer domain questions from its own knowledge.
- Prefer the fewest agents that can answer. Single-domain questions go to one agent.
- Ask a clarifying question when the request is too vague to plan, for example "How are we doing?".
- The synthesis must say plainly when a part could not be answered, and which agent failed.

Streaming: the graph emits the events in `core/events.py`: `plan`, `agent_started`, `tool_call`, `peer_message`, `agent_result`, `eval_result`, `final`, `clarification` and `error`. FastAPI forwards them as SSE.

---

## 7. Department agents

Each agent folder contains:
- `card.py` — its `AgentCard`;
- `tools.py` — LangChain tools. These may only import `app.data.repositories.<own>` and `app.data.repositories.reference` (Tech may also import `app.integrations.github_client`);
- `prompts.py` — system prompt: domain scope, evidence rules, when to use `ask_agent`, refusal rules for out-of-domain data;
- `agent.py` — subclasses `DepartmentAgent` and calls `registry.register(...)`.

Minimum tools (read-only, all return structured data including record ids for evidence):

**Finance:** `get_project_budget(project_id, period)`, `get_project_spend(project_id, start, end)`, `budget_vs_actual(period, department_id?)`, `expenses_by_category(project_id?, start, end)`, `people_cost(employee_ids | project_id, period)`, `top_overruns(period, n)`.

**HR:** `get_employee(id | github_username)`, `project_staffing(project_id)`, `employee_allocations(employee_id)`, `over_allocated(threshold_pct)`, `leave_overlap(project_id, start, end)`, `open_positions(department_id?)`, `headcount_by_department(as_of)`.

**Tech:** `list_projects(status?)`, `project_delivery_status(project_id)` (planned vs expected dates, DB), `repo_activity(repo, since)` (commits, last push), `open_issues(repo)`, `open_pulls(repo)`, `stale_repos(days)`, `contributors(repo)`.

Planned-dependency example the tests must cover: Tech finds a stalled repo, asks HR who is allocated to that project, and HR returns staffing and leave overlap. The CEO separately asks Finance for budget vs actual on the same project.

---

## 8. Evaluation hooks (stubs only)

`core/eval_hooks.py` defines the interfaces the next phase will implement:

```python
async def self_check(result: AgentResult, subtask: Subtask) -> EvalResult      # stub: passed=True, stage="self"
async def independent_eval(result: AgentResult, subtask: Subtask) -> EvalResult  # stub: passed=True, stage="independent"
async def evidence_check(result: AgentResult) -> EvalResult                     # stub: passes only if result.evidence is non-empty or status != "ok"
def recovery_router(eval_result: EvalResult) -> Literal["pass", "retry", "replan", "clarify"]  # stub: always "pass"
```

Wire them into the graph now (`self_check` at the end of each department subgraph, `independent_eval` and `evidence_check` in `eval_gate`) so that the next phase only replaces function bodies. Log every `EvalResult` to Langfuse as a score and emit an `eval_result` SSE event. Reserve the `GEMINI_JUDGE_MODEL` setting for the judge, which must be a different model from the agents.

---

## 9. LLM layer (`core/llm.py`)

- One factory, `get_llm(role: Literal["ceo", "agent", "judge"])`, returns `ChatGoogleGenerativeAI` configured from env. **Do not hardcode model names.** Check which Gemini models are currently available on the free tier and put them in `.env.example`.
- **The free tier is tightly rate-limited, and parallel fan-out will hit it.** Use one shared `InMemoryRateLimiter` (from `langchain_core.rate_limiters`) across every model instance, driven by `LLM_REQUESTS_PER_SECOND`. Also cap concurrent agent runs with an asyncio semaphore (`LLM_MAX_CONCURRENCY`, default 2).
- Retry with exponential backoff on 429 and 5xx errors only (`LLM_MAX_RETRIES`, default 4). Surface exhausted retries as `AgentResult(status="failed")`.
- `temperature=0` for the CEO planner and agents.
- Use structured output for plans and `AgentResult`s.

---

## 10. Data layer and seed

`DATABASE_URL=sqlite:///./data/org.db`. Use SQLAlchemy 2.x models and write every query in `repositories/`. Agents and tools never touch sessions or SQL directly. Use only portable SQL, with no SQLite-specific features, so that moving to Supabase later is a `DATABASE_URL` change plus Alembic.

Tables: `departments`, `employees` (includes nullable `github_username`), `projects` (`repo_full_name`, `department_id`, `lead_employee_id`, `status`, `priority`, `planned_start`, `planned_end`), `allocations`, `leave`, `open_positions`, `budgets` (per project per quarter), `expenses`, `payroll` (monthly cost per employee, owned by Finance, not HR), `a2a_messages`, `github_cache`.

`seed/seed.py` (runnable as `uv run python -m app.data.seed.seed`):
1. Fetches the repos of `GITHUB_OWNER` (the developer's own account) through `github_client`. If there is no token, it falls back to `fixtures_repos.json`.
2. Creates one project per repo (cap at `SEED_MAX_REPOS`, default 12), spread across 4 departments (Engineering, Product, Data, Operations).
3. Generates about 40 employees with Faker using a fixed seed (`SEED=42`), along with allocations, leave, payroll, quarterly budgets, expenses and open positions over the last 4 quarters. Currency comes from `CURRENCY` (default `INR`).
4. Maps the account owner's GitHub username to one synthetic employee. The remaining employees get `github_username = NULL`. Do not invent usernames that could collide with real people.
5. **Plants known scenarios** and writes them to `scenarios.json` as ground truth for later benchmarks. Plant at least: one project over budget with adequate staff, one within budget but understaffed (over-allocated lead plus overlapping leave), one with both problems, one healthy project, and one project whose repo has had no push in over 60 days. For planted delivery delays, use the real repo activity where it fits, and otherwise mark the delay in the project's `planned_end` vs `status`.
6. Is idempotent: `--reset` drops and recreates the database.

---

## 11. GitHub client (`integrations/github_client.py`)

- Uses `httpx`, and implements GET only. It must have no `post`, `put`, `patch` or `delete` methods, and `test_github_readonly.py` asserts this.
- Uses a fine-grained PAT with read-only scopes (metadata, contents, issues, pull requests) for `GITHUB_OWNER`.
- Caches responses in `github_cache` with a TTL (`GITHUB_CACHE_TTL_SECONDS`, default 900), and respects rate-limit headers.
- Returns typed results that include the API path, so tools can build `Evidence(source_type="github")`.

---

## 12. Observability (Langfuse Cloud)

- Use the Langfuse LangChain callback handler, attached at the top-level graph invoke so every node, tool and LLM call is traced.
- One trace per stakeholder request. `session_id` is the conversation id. Tags: agent names involved.
- Peer calls appear as nested spans named `a2a:{sender}->{recipient}`, with metadata for `hop_count` and `chain`.
- Eval stub results are recorded as Langfuse scores.
- The `final` SSE event includes the Langfuse trace URL so the UI can link to it.
- If Langfuse keys are missing, the app still runs, logs a warning and skips tracing.

---

## 13. API (`app/api/routes.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/chat` | Body `{conversation_id?, message}`. Returns an SSE stream of `core/events.py` events |
| GET | `/api/agents` | All registered `AgentCard`s |
| GET | `/api/conversations` | List of conversations |
| GET | `/api/conversations/{id}` | Messages plus final answers |
| GET | `/api/conversations/{id}/a2a` | A2A message log for the conversation |
| GET | `/api/health` | DB, GitHub token and Langfuse status |

CORS is allowed for `http://localhost:5173` only.

---

## 14. Frontend

Vite + React + TS + Tailwind, in `frontend/`. Types in `src/types/` mirror `contracts.py` and `events.py` exactly.

Screens:
1. **Chat.** A streaming conversation. While a request runs, show the CEO plan (subtasks and assigned agents), each agent's status, and the final answer with expandable evidence per claim. Clarification questions render as a normal assistant turn.
2. **A2A activity panel.** Sits beside the chat and shows a live timeline of `task`, `peer_request` and `peer_response` messages, displaying sender → recipient, hop count, and any refusals (hop limit or cycle).
3. **Agents page.** Cards for each registered agent, with skills and owned data.
4. **Conversation history** list.

Also: a link to the Langfuse trace on each answer, empty/loading/error states, and no component libraries beyond Tailwind (lucide-react for icons is fine).

---

## 15. Environment (`.env.example`)

```
GOOGLE_API_KEY=
GEMINI_CEO_MODEL=           # verify current free-tier model ids
GEMINI_AGENT_MODEL=
GEMINI_JUDGE_MODEL=         # reserved for next phase; must differ from agent model
LLM_REQUESTS_PER_SECOND=0.2
LLM_MAX_CONCURRENCY=2
LLM_MAX_RETRIES=4

LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

GITHUB_TOKEN=               # fine-grained PAT, read-only
GITHUB_OWNER=
GITHUB_CACHE_TTL_SECONDS=900

DATABASE_URL=sqlite:///./data/org.db
SEED=42
SEED_MAX_REPOS=12
CURRENCY=INR

MAX_PEER_HOPS=2
MAX_PEER_CALLS_PER_AGENT=3
GRAPH_RECURSION_LIMIT=40
```

Never commit `.env`.

---

## 16. Build plan and how to use subagents

The build runs in three phases. **Do not start Phase 1 until the Phase 0 exit criteria pass.**

### Phase 0 — Core (main session, sequential)

Build everything under `app/core/`, `app/data/`, `app/integrations/`, `app/main.py`, `app/api/`, `.env.example` and `pyproject.toml`. Specifically: config, LLM factory with rate limiter, contracts, events, state, registry, `DepartmentAgent` base, `a2a.py` with all guards, eval stubs, observability, orchestrator skeleton, DB models and repositories, seed script, GitHub client, and a minimal `/api/health`.

Also write a throwaway `EchoAgent` in `tests/` that registers through the registry. Use it to prove the orchestrator, `ask_agent` guards and SSE work with no real department agents.

Exit criteria:
- `uv run pytest tests/core` passes, including guard tests for hop limit, cycle, self-call, unknown target and call limit;
- `test_github_readonly.py` passes;
- the seed runs and writes `scenarios.json`;
- `/api/health` responds;
- contracts and events are final.

Then write `frontend/src/types/` from the contracts so that the frontend subagent has a fixed interface.

### Phase 1 — Agents and frontend (parallel subagents)

Launch these subagents from `.claude/agents/` in parallel. Each one works only inside its folder:

| Subagent | Writes only to |
|---|---|
| `ceo-agent-builder` | `backend/app/agents/ceo/`, `backend/tests/agents/ceo/` |
| `finance-agent-builder` | `backend/app/agents/finance/`, `backend/tests/agents/finance/` |
| `hr-agent-builder` | `backend/app/agents/hr/`, `backend/tests/agents/hr/` |
| `tech-agent-builder` | `backend/app/agents/tech/`, `backend/tests/agents/tech/` |
| `frontend-builder` | `frontend/` |

Rules for every subagent:
- Never edit `app/core/`, `app/data/`, `app/integrations/`, `app/api/` or another agent's folder.
- If a contract or repository function is missing, stop and report exactly what is needed. The main session makes core changes.
- Tools must return record ids so that evidence can be built.
- Unit-test tools against a seeded test database. Mock the LLM in unit tests. Never call Gemini in unit tests.

### Phase 2 — Integration (main session)

1. Import all agent modules in `app/agents/__init__.py` so that they register.
2. Wire `/api/chat` streaming end to end, plus the remaining API routes.
3. Write `test_data_ownership.py`. It inspects each agent's `tools.py` imports and fails if any agent imports another department's repository.
4. Write `test_e2e_questions.py`, marked `@pytest.mark.live` and skipped unless `GOOGLE_API_KEY` is set, using these questions against the seeded data:
   1. "Which technology projects are behind schedule, and is the cause people or budget?" → CEO uses Tech, HR and Finance; at least one peer message is expected.
   2. "What is our spend versus budget on <planned over-budget project> this quarter?" → Finance only.
   3. "Who is working on the repo with the most open issues, and are they over-allocated?" → Tech asks HR as a peer.
   4. "Which department's people cost grew most last quarter?" → Finance, possibly asking HR.
   5. "How are we doing?" → clarification, no agents dispatched.
5. Verify in Langfuse that the traces show nested `a2a:` spans and eval stub scores.
6. Write `README.md`: setup (uv, npm), `.env` creation, creating the fine-grained GitHub PAT, seeding, running backend and frontend, and running tests.

### Done means
- `uv run pytest` passes (live tests skipped without a key).
- `uv run uvicorn app.main:app --reload` and `npm run dev` start cleanly.
- All five e2e questions produce sensible answers with evidence when run live.
- Adding a dummy fourth department in a test, without touching `app/core/`, works and appears in `/api/agents`.

---

## 17. Coding conventions

- Async throughout the backend (async SQLAlchemy with `aiosqlite`, async graph invokes).
- Type hints everywhere. Run `ruff check` and `ruff format` before finishing any task.
- No business logic in routes. Routes call the orchestrator.
- Prompts live in `prompts.py` files, not inline.
- Log with the stdlib `logging` module, including `request_id` in every record.
- Keep functions small. Prefer clear names over comments.
- Do not add dependencies beyond the stack without stating why in the task summary.

## 18. Next phases (not now, design for them)

Self-evaluation and the independent judge (separate Gemini model), evidence checks that block responses, retry/replan/clarify recovery, memory, Supabase migration, Railway deployment, and benchmark experiments comparing collaborative and isolated agents using `scenarios.json` as ground truth.
