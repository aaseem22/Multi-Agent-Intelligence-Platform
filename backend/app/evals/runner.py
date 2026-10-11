"""Offline eval harness: run the selected golden tasks k times each against a freshly seeded
fixture database and grade every trial.

    create_run(config)   -> writes config.json, run.json (queued), progress.json
    execute_run(run_id)  -> seeds <run_dir>/org.db, runs every trial sequentially, writes
                            trials/<trial_id>.json, progress.json and finally run.json

`execute_run` is what the subprocess (`python -m app.evals.run --run-id ...`) calls; tests call it
in-process with scripted agents. One event loop serves the whole run: the Gemini SDK binds its
async clients to the loop that created them, so a fresh loop per trial would hang.

Isolation: one database per run (domain data is read-only, so trials cannot change ground truth),
and per trial a new Orchestrator with an in-memory checkpointer and a new conversation, so no
history or A2A call counters leak between trials."""

import asyncio
import importlib
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import get_settings
from app.core.contracts import utcnow
from app.core.orchestrator import Orchestrator
from app.data import db
from app.evals.contracts import EvalTask, RunConfig, RunProgress, RunSummary, TrialResult
from app.evals.datasets import load_dataset, select_tasks
from app.evals.facts import FactContext, build_context
from app.evals.graders import GradingContext, run_graders
from app.evals.scoring import aggregate, trial_passed, weighted_score
from app.evals.storage import RunStore
from app.evals.transcript import TrialView

logger = logging.getLogger(__name__)

TRIAL_TIMEOUT_SECONDS = 900
FIXTURE_SEED = 42
FIXTURE_MAX_REPOS = 12
FIXTURE_CURRENCY = "INR"

AgentLoader = Callable[[], None | Awaitable[None]]


# --- LLM call counting (every chat model start inside the trial's context) ---


class LLMCallCounter(BaseCallbackHandler):
    run_inline = True

    def __init__(self) -> None:
        self.calls = 0

    def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        self.calls += 1

    def on_llm_start(self, *args: Any, **kwargs: Any) -> None:
        self.calls += 1


_llm_counter: ContextVar[LLMCallCounter | None] = ContextVar("eval_llm_counter", default=None)
register_configure_hook(_llm_counter, True)


# --- run lifecycle ---


def new_run_id() -> str:
    return f"{utcnow():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def judge_model_name() -> str:
    settings = get_settings()
    return (
        settings.groq_judge_model
        if settings.judge_provider == "groq"
        else settings.gemini_judge_model
    )


def estimate_llm_calls(task: EvalTask) -> int:
    """Rough LLM calls per trial: planner + synthesis + ~4 per agent, +4 per expected peer hop."""
    if task.expected.clarification:
        return 1
    agents = max(1, len(task.expected.agents_required))
    return 2 + 4 * agents + (4 if task.expected.peer_messages == "required" else 0)


def estimate_seconds(tasks: list[EvalTask], trials: int) -> int:
    rps = get_settings().llm_requests_per_second or 0.2
    calls = sum(estimate_llm_calls(t) for t in tasks) * trials
    return int(calls / rps)


def create_run(
    config: RunConfig,
    *,
    run_id: str | None = None,
    root: Path | None = None,
    datasets_dir: Path | None = None,
) -> RunSummary:
    """Validate the selection and write a queued run. Raises DatasetError for a bad config."""
    dataset = load_dataset(config.dataset, datasets_dir)
    tasks = select_tasks(dataset, config)
    settings = get_settings()
    store = RunStore(run_id or new_run_id(), root)
    store.dir.mkdir(parents=True, exist_ok=True)
    now = utcnow()
    summary = RunSummary(
        run_id=store.run_id,
        status="queued",
        config=config,
        dataset_version=dataset.version,
        agent_model=settings.gemini_agent_model,
        ceo_model=settings.gemini_ceo_model,
        judge_model=judge_model_name(),
        created_at=now,
        tasks_total=len(tasks),
        trials_total=len(tasks) * config.trials,
    )
    store.write_config(config)
    store.write_summary(summary)
    seconds = estimate_seconds(tasks, config.trials)
    store.write_progress(
        RunProgress(
            run_id=store.run_id,
            status="queued",
            trials_total=summary.trials_total,
            trials_done=0,
            message=f"queued; estimated duration ~{seconds // 60} min",
            updated_at=now,
        )
    )
    return summary


@contextmanager
def fixture_settings(**extra: Any) -> Iterator[None]:
    """Fixture seed and offline GitHub so ground truth matches the golden dataset; restored after."""
    settings = get_settings()
    overrides: dict[str, Any] = {
        "github_token": "",
        "seed": FIXTURE_SEED,
        "seed_max_repos": FIXTURE_MAX_REPOS,
        "currency": FIXTURE_CURRENCY,
        **extra,
    }
    previous = {key: getattr(settings, key) for key in overrides}
    for key, value in overrides.items():
        setattr(settings, key, value)
    try:
        yield
    finally:
        for key, value in previous.items():
            setattr(settings, key, value)


def _run_settings(config: RunConfig):
    """Fixture settings plus the run's self-evaluation switches (recovery mode, live judge)."""
    return fixture_settings(
        eval_recovery=config.self_eval_recovery, eval_judge_enabled=config.judge_enabled
    )


async def seed_fixture_database(directory: Path) -> dict[str, Any]:
    """Seed <directory>/org.db from offline fixtures and return its scenarios.json.
    Leaves the data layer pointed at that database; the caller restores it."""
    from app.data.seed import seed as seed_module

    os.makedirs(directory, exist_ok=True)
    db.configure_database(f"sqlite+aiosqlite:///{directory / 'org.db'}")
    original = seed_module.SCENARIOS_PATH
    seed_module.SCENARIOS_PATH = directory / "scenarios.json"
    settings = get_settings()
    token = settings.github_token
    settings.github_token = ""
    try:
        scenarios = await seed_module.seed(reset=True)
    finally:
        seed_module.SCENARIOS_PATH = original
        settings.github_token = token
    if scenarios is None:
        scenarios = json.loads((directory / "scenarios.json").read_text())
    return scenarios


def _print(message: str) -> None:
    print(message, flush=True)


def load_default_agents() -> None:
    importlib.import_module("app.agents")


async def run_trial(task: EvalTask, *, run_id: str, index: int, judge_enabled: bool) -> TrialResult:
    """One attempt at a (resolved) task in a clean orchestrator; graded immediately."""
    started_at = utcnow()
    events: list[dict[str, Any]] = []
    error: str | None = None
    counter = LLMCallCounter()
    orchestrator = Orchestrator(checkpointer=InMemorySaver())
    started = time.monotonic()
    token = _llm_counter.set(counter)
    try:
        await orchestrator.start()
        async with asyncio.timeout(TRIAL_TIMEOUT_SECONDS):
            async for event in orchestrator.stream(task.question):
                events.append(event.model_dump(mode="json"))
    except TimeoutError:
        error = f"trial timed out after {TRIAL_TIMEOUT_SECONDS}s"
    except Exception as exc:
        logger.exception("Trial %s/%d crashed", task.id, index)
        error = f"{type(exc).__name__}: {exc}"
    finally:
        _llm_counter.reset(token)
        await orchestrator.aclose()  # also cancels a request left running by a timeout
    duration_ms = int((time.monotonic() - started) * 1000)
    view = TrialView(events, duration_ms=duration_ms, llm_calls=counter.calls)
    graders = await run_graders(
        task.graders, GradingContext(task=task, trial=view, judge_enabled=judge_enabled)
    )
    score = weighted_score(graders)
    passed = error is None and trial_passed(graders)
    return TrialResult(
        trial_id=f"{task.id}__{index}",
        run_id=run_id,
        task_id=task.id,
        index=index,
        status="error" if error else ("passed" if passed else "failed"),
        score=score,
        passed=passed,
        graders=graders,
        question=task.question,
        final_answer=view.final_answer,
        clarification=view.clarification if view.final is None else None,
        agents_planned=view.planned_agents,
        peer_requests=len(view.peer_requests),
        refusals=len(view.refusals),
        recoveries=len(view.recoveries),
        duration_ms=duration_ms,
        llm_calls=counter.calls,
        error=error,
        trace_url=view.trace_url,
        transcript=events,
        started_at=started_at,
        finished_at=utcnow(),
    )


def _progress(
    store: RunStore, summary: RunSummary, message: str, current_task: str | None = None
) -> None:
    store.write_progress(
        RunProgress(
            run_id=summary.run_id,
            status=summary.status,
            trials_total=summary.trials_total,
            trials_done=summary.trials_done,
            current_task=current_task,
            message=message,
            updated_at=utcnow(),
        )
    )


def _finish(
    store: RunStore, summary: RunSummary, status: str, message: str, error: str | None = None
) -> RunSummary:
    summary = summary.model_copy(update={"status": status, "finished_at": utcnow(), "error": error})
    store.write_summary(summary)
    _progress(store, summary, message)
    return summary


async def execute_run(
    run_id: str,
    *,
    root: Path | None = None,
    datasets_dir: Path | None = None,
    load_agents: AgentLoader = load_default_agents,
    echo: Callable[[str], None] | None = None,
) -> RunSummary:
    echo = echo or _print
    store = RunStore(run_id, root)
    config = store.read_config()
    summary = store.read_summary()
    if summary is None:
        raise FileNotFoundError(f"run {run_id} has no run.json; create it first")
    previous_db = db._url_override
    try:
        with _run_settings(config):
            return await _execute(store, config, summary, datasets_dir, load_agents, echo)
    except Exception as exc:
        logger.exception("Run %s failed", run_id)
        return _finish(store, summary, "failed", "run failed", f"{type(exc).__name__}: {exc}")
    finally:
        await db.dispose_engine()
        db.configure_database(previous_db)


async def _execute(
    store: RunStore,
    config: RunConfig,
    summary: RunSummary,
    datasets_dir: Path | None,
    load_agents: AgentLoader,
    echo: Callable[[str], None],
) -> RunSummary:
    dataset = load_dataset(config.dataset, datasets_dir)
    tasks = select_tasks(dataset, config)
    summary = summary.model_copy(update={"status": "running", "started_at": utcnow()})
    store.write_summary(summary)
    _progress(store, summary, "seeding the fixture database")
    scenarios = await seed_fixture_database(store.dir)
    loaded = load_agents()
    if asyncio.iscoroutine(loaded):
        await loaded
    facts: FactContext = await build_context(scenarios)
    resolved = [facts.resolve_task(t) for t in tasks]
    seconds = estimate_seconds(resolved, config.trials)
    echo(
        f"Run {summary.run_id}: {len(resolved)} task(s) x {config.trials} trial(s), "
        f"estimated ~{seconds // 60} min {seconds % 60} s at "
        f"{get_settings().llm_requests_per_second} LLM requests/s"
    )
    trials: list[TrialResult] = []
    for task in resolved:
        for index in range(config.trials):
            if store.cancel_path.exists():
                return _finish(store, summary, "cancelled", "cancelled by user")
            _progress(
                store, summary, f"running {task.id} trial {index + 1}/{config.trials}", task.id
            )
            trial = await run_trial(
                task, run_id=summary.run_id, index=index, judge_enabled=config.judge_enabled
            )
            store.write_trial(trial)
            trials.append(trial)
            echo(
                f"  {trial.trial_id}: {trial.status} score={trial.score:.2f} "
                f"llm={trial.llm_calls} {trial.duration_ms / 1000:.1f}s"
                + (f" error={trial.error}" if trial.error else "")
            )
            summary = summary.model_copy(update=aggregate(resolved, trials))
            store.write_summary(summary)
            _progress(store, summary, f"finished {trial.trial_id}", task.id)
    summary = _finish(store, summary, "completed", "completed")
    echo(
        f"Run {summary.run_id} completed: pass_rate={summary.pass_rate} "
        f"pass@k={summary.pass_at_k} pass^k={summary.pass_hat_k} mean_score={summary.mean_score}"
    )
    return summary
