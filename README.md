# Multi-Agent Intelligence Platform

A stakeholder asks a cross-department question in plain language. A CEO agent plans subtasks and
dispatches them in parallel to Finance, HR and Tech agents. Department agents answer from their
own data and ask each other directly (agent-to-agent, A2A) when they need data another
department owns. The CEO combines the results into one answer, and every claim cites evidence.

The build specification is [CLAUDE.md](CLAUDE.md). This README covers running the project.

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- A Google AI Studio API key (Gemini free tier)
- Optional: a Langfuse Cloud project, and a GitHub fine-grained token

## 1. Configure `.env`

```bash
cp .env.example .env
```

Put `.env` in the repo root and never commit it. At minimum, set `GOOGLE_API_KEY`. The default
model ids in `.env.example` were on the free tier in September 2026. Check your limits in
[AI Studio](https://aistudio.google.com/rate-limit). `GEMINI_JUDGE_MODEL` is reserved for the
next phase and must differ from `GEMINI_AGENT_MODEL`.

Without Langfuse keys, the app runs and skips tracing. Without a GitHub token, the app uses
recorded offline data from `backend/app/data/seed/fixtures_repos.json`.

### GitHub fine-grained token (read-only)

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens →
   **Generate new token**.
2. Resource owner: your account. Repository access: all repositories, or the ones to use.
3. Repository permissions, all **Read-only**: Metadata, Contents, Issues, Pull requests.
4. Set `GITHUB_TOKEN=<token>` and `GITHUB_OWNER=<your username>` in `.env`.

The client can only send GET requests; `tests/test_github_readonly.py` enforces this.

## 2. Backend

```bash
cd backend
uv sync
uv run python -m app.data.seed.seed --reset   # builds data/org.db and scenarios.json
uv run uvicorn app.main:app --reload          # http://localhost:8000
```

The seed builds a fictional organisation around your repositories: 4 departments, about 40
employees, budgets, expenses, payroll and leave. It also plants known scenarios as ground truth
in `backend/app/data/seed/scenarios.json`, such as an over-budget project, an understaffed
project, a stale repo and a department whose people cost grew. It is deterministic (`SEED=42`).

Check it is running: `curl localhost:8000/api/health`.

## 3. Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173, proxies /api to :8000
VITE_USE_MOCK=true npm run dev       # UI demo with a recorded event stream, no backend
```

## 4. Tests

```bash
cd backend
uv run pytest                        # unit + integration; mocked LLM, offline GitHub
uv run pytest -m live -s             # 5 end-to-end questions against real Gemini (needs key)
uv run ruff check && uv run ruff format --check
```

```bash
cd frontend
npm run build && npm run lint
```

The live questions run at `LLM_REQUESTS_PER_SECOND` (default 0.2), so a full live run takes
several minutes.

## Architecture in brief

| Path | What it is |
|---|---|
| `backend/app/core/` | Department-agnostic runtime: contracts, registry, `DepartmentAgent` base, `ask_agent` with its guards, orchestrator graph, eval hook stubs, Langfuse |
| `backend/app/agents/<name>/` | One folder per agent: `card.py`, `tools.py`, `prompts.py`, `agent.py` |
| `backend/app/data/` | SQLAlchemy models, one repository module per data owner, seed |
| `backend/app/integrations/github_client.py` | GET-only GitHub client with a SQLite response cache |
| `frontend/src/types/` | TypeScript mirror of `contracts.py` and `events.py` |

**A2A guards.** Peer delegation always terminates. A request is refused if it would exceed
`MAX_PEER_HOPS`, exceed `MAX_PEER_CALLS_PER_AGENT` per request, revisit an agent already in the
chain, target the caller itself, target an unknown agent, or target the CEO. Refusals come back
to the calling agent as text, and the UI timeline shows them.

**Evidence.** Tools return records with a `source_ref` such as `budgets:id=12`. An agent's final
answer can cite only refs that its tools or peers actually returned, so evidence cannot be
invented.

**Adding a department.** Create `backend/app/agents/<name>/` with a card, tools that import only
its own repository, a prompt, and an `agent.py` that calls `registry.register(...)`. Then add one
import line to `backend/app/agents/__init__.py`. Nothing in `app/core/` changes, and
`tests/test_data_ownership.py` checks the imports.

## Out of scope for this phase

Self-evaluation, the independent judge, retry and replan recovery, memory, Supabase and
deployment. The hook points exist in `backend/app/core/eval_hooks.py`.
