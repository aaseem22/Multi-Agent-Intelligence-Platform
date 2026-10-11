"""/api/evals routes through httpx's ASGI transport. The runner subprocess is replaced by a fake
process; trials and labels are written to a temporary evals_dir."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.judge import JudgeVerdict
from app.core.orchestrator import Orchestrator
from app.data.repositories import platform
from app.evals import service
from app.evals.contracts import GraderResult, RunConfig, TrialResult
from app.evals.runner import create_run
from app.evals.storage import RunStore
from app.main import create_app


class FakeProcess:
    pid = 999_999

    def __init__(self) -> None:
        self.running = True
        self.terminated = False

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[FakeProcess]:
    processes: list[FakeProcess] = []

    def fake_spawn(run_id: str) -> FakeProcess:
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(service, "spawn_runner", fake_spawn)
    monkeypatch.setattr(service, "_processes", {})
    return processes


@pytest.fixture
async def client(evals_root):
    orchestrator = Orchestrator(checkpointer=InMemorySaver())
    app = create_app(orchestrator)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


def judged(name: str, passed: bool) -> GraderResult:
    verdict = JudgeVerdict(
        rubric=name, passed=passed, score=1.0 if passed else 0.0, dimensions=[], model="m"
    )
    return GraderResult(
        grader=name, kind="model", passed=passed, score=verdict.score, judge=verdict
    )


def write_trial(run_id: str, trial_id: str, graders: list[GraderResult]) -> TrialResult:
    trial = TrialResult(
        trial_id=trial_id,
        run_id=run_id,
        task_id=trial_id.split("__")[0],
        index=0,
        status="passed",
        score=1.0,
        passed=True,
        graders=graders,
        question="q",
        transcript=[{"type": "final"}],
        started_at=datetime.now(UTC),
    )
    RunStore(run_id).write_trial(trial)
    return trial


async def test_datasets(client) -> None:
    response = await client.get("/api/evals/datasets")
    assert response.status_code == 200
    assert "golden" in [d["name"] for d in response.json()]


async def test_start_run_conflict_progress_and_cancel(client, spawned) -> None:
    body = {"suites": ["regression"], "trials": 1, "judge_enabled": False}
    response = await client.post("/api/evals/runs", json=body)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "queued" and run["config"]["judge_enabled"] is False
    assert run["tasks_total"] > 0 and len(spawned) == 1

    assert (await client.post("/api/evals/runs", json=body)).status_code == 409

    listed = (await client.get("/api/evals/runs")).json()
    assert [r["run_id"] for r in listed] == [run["run_id"]]
    progress = (await client.get(f"/api/evals/runs/{run['run_id']}/progress")).json()
    assert progress["status"] == "queued" and progress["trials_total"] == run["trials_total"]

    assert (await client.post(f"/api/evals/runs/{run['run_id']}/cancel")).status_code == 204
    assert spawned[0].terminated
    assert (await client.get(f"/api/evals/runs/{run['run_id']}")).json()["status"] == "cancelled"
    # the slot is free again
    assert (await client.post("/api/evals/runs", json=body)).status_code == 200


async def test_dead_runner_is_reported_failed_and_frees_the_slot(client, spawned) -> None:
    body = {"task_ids": ["reg-q5-clarify-vague"]}
    run = (await client.post("/api/evals/runs", json=body)).json()
    spawned[0].running = False  # crashed without writing a final status
    detail = (await client.get(f"/api/evals/runs/{run['run_id']}")).json()
    assert detail["status"] == "failed" and "exited unexpectedly" in detail["error"]
    assert (await client.post("/api/evals/runs", json=body)).status_code == 200


async def test_invalid_configs_are_422(client, spawned) -> None:
    assert (await client.post("/api/evals/runs", json={"trials": 9})).status_code == 422
    assert (await client.post("/api/evals/runs", json={"dataset": "nope"})).status_code == 422
    assert (await client.post("/api/evals/runs", json={"task_ids": ["x"]})).status_code == 422
    assert spawned == []


async def test_unknown_ids_are_404(client) -> None:
    for path in (
        "/api/evals/runs/missing",
        "/api/evals/runs/missing/progress",
        "/api/evals/runs/missing/trials",
        "/api/evals/runs/missing/labels",
        "/api/evals/runs/missing/trials/x__0",
    ):
        assert (await client.get(path)).status_code == 404, path
    assert (await client.post("/api/evals/runs/missing/cancel")).status_code == 404
    run = create_run(RunConfig(task_ids=["reg-q5-clarify-vague"]))
    assert (await client.get(f"/api/evals/runs/{run.run_id}/trials/nope__0")).status_code == 404
    label = {"trial_id": "nope__0", "grader": "reference_match", "human_passed": True}
    assert (
        await client.post(f"/api/evals/runs/{run.run_id}/labels", json=label)
    ).status_code == 404


async def test_trials_list_strips_transcripts(client) -> None:
    run = create_run(RunConfig(task_ids=["reg-q5-clarify-vague"]))
    write_trial(run.run_id, "reg-q5-clarify-vague__0", [judged("reference_match", True)])
    listed = (await client.get(f"/api/evals/runs/{run.run_id}/trials")).json()
    assert listed[0]["transcript"] == []
    detail = (
        await client.get(f"/api/evals/runs/{run.run_id}/trials/reg-q5-clarify-vague__0")
    ).json()
    assert detail["transcript"] == [{"type": "final"}]


async def test_labels_upsert_and_calibration(client) -> None:
    run = create_run(RunConfig(task_ids=["reg-q5-clarify-vague"]))
    write_trial(
        run.run_id,
        "a__0",
        [judged("reference_match", True), judged("answer_groundedness", False)],
    )
    write_trial(run.run_id, "b__0", [judged("reference_match", True)])
    skipped = GraderResult(
        grader="answer_completeness",
        kind="model",
        passed=True,
        score=0.0,
        weight=0.0,
        details={"skipped": True},
    )
    write_trial(run.run_id, "c__0", [skipped])
    url = f"/api/evals/runs/{run.run_id}/labels"

    def post(trial_id: str, grader: str, human: bool):
        return client.post(
            url, json={"trial_id": trial_id, "grader": grader, "human_passed": human}
        )

    assert (await post("a__0", "reference_match", False)).status_code == 200
    response = await post("a__0", "reference_match", True)  # upsert replaces the first label
    assert response.json()["human_passed"] is True
    await post("a__0", "answer_groundedness", True)  # judge failed, human passed
    await post("b__0", "reference_match", False)  # judge passed, human failed
    await post("c__0", "answer_completeness", True)  # skipped verdict: not comparable
    labels = (await client.get(url)).json()
    assert len(labels) == 4

    stats = (await client.get("/api/evals/calibration")).json()
    assert stats["labels"] == 3
    assert stats["agreement"] == pytest.approx(1 / 3, abs=1e-3)
    assert stats["judge_false_pass"] == 1 and stats["judge_false_fail"] == 1
    assert stats["by_grader"] == {"answer_groundedness": 0.0, "reference_match": 0.5}


async def test_self_eval_stats(client) -> None:
    async def record(**fields) -> None:
        await platform.log_eval_record(conversation_id="c", agent="tech", **fields)

    await record(
        request_id="r1", kind="eval", subtask_id="t1", stage="independent", passed=False, attempt=1
    )
    await record(request_id="r1", kind="recovery", subtask_id="t1", action="retry", attempt=2)
    await record(
        request_id="r1", kind="eval", subtask_id="t1", stage="independent", passed=True, attempt=2
    )
    await record(
        request_id="r2",
        kind="eval",
        subtask_id="t1",
        stage="independent",
        passed=True,
        payload={"judge": {"error": "quota"}},
    )
    await record(request_id="r3", kind="eval", subtask_id="t1", stage="independent", passed=False)
    await record(request_id="r3", kind="recovery", subtask_id="t1", action="retry", attempt=2)
    await record(request_id="r3", kind="eval", subtask_id="t1", stage="evidence", passed=True)

    stats = (await client.get("/api/evals/self-eval?days=7")).json()
    assert stats["window_days"] == 7
    assert stats["evaluations"] == 5
    assert stats["by_stage"] == {"evidence": 1.0, "independent": 0.5}
    assert stats["retries"] == 2
    assert stats["retry_success_rate"] == 0.5  # r1 recovered, r3 did not
    assert stats["judge_errors"] == 1
    assert len(stats["recent"]) == 7
    assert (await client.get("/api/evals/self-eval?days=0")).status_code == 422


def test_summarise_self_eval_empty() -> None:
    stats = service.summarise_self_eval([], 7)
    assert stats.evaluations == 0 and stats.retry_success_rate is None and stats.by_stage == {}


def test_queued_run_without_process_goes_stale(evals_root) -> None:
    run = create_run(RunConfig(task_ids=["reg-q5-clarify-vague"]))
    store = RunStore(run.run_id)
    store.write_summary(run.model_copy(update={"created_at": run.created_at - timedelta(hours=1)}))
    assert service.get_run(run.run_id).status == "failed"
