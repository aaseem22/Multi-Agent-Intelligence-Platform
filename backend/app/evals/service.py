"""Evals service used by /api/evals routes: datasets, runs (spawned as a subprocess so the API's
own database is never touched), progress, trials, human labels, judge calibration and live
self-evaluation statistics. One run at a time: the Gemini free tier cannot sustain two."""

import logging
import os
import signal
import subprocess
import sys
import threading
from collections import defaultdict
from datetime import timedelta
from typing import Any

from app.core.config import BACKEND_DIR
from app.core.contracts import utcnow
from app.evals.contracts import (
    CalibrationStats,
    Dataset,
    HumanLabel,
    RunConfig,
    RunProgress,
    RunSummary,
    SelfEvalStats,
    TrialResult,
)
from app.evals.datasets import DatasetError, list_datasets
from app.evals.graders import is_skipped
from app.evals.runner import create_run
from app.evals.storage import RunStore, is_safe_id, runs_dir

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running")
QUEUED_GRACE = timedelta(minutes=2)
RECENT_SELF_EVAL = 50


class NotFoundError(LookupError):
    pass


class RunConflictError(RuntimeError):
    pass


class InvalidConfigError(ValueError):
    pass


_processes: dict[str, Any] = {}
_lock = threading.Lock()


def spawn_runner(run_id: str) -> subprocess.Popen[bytes]:
    """Start `python -m app.evals.run --run-id <id>` detached from the API's event loop."""
    store = RunStore(run_id)
    log = store.log_path.open("ab")
    try:
        return subprocess.Popen(
            [sys.executable, "-m", "app.evals.run", "--run-id", run_id],
            cwd=BACKEND_DIR,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log.close()


# --- process liveness ---


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(store: RunStore) -> int | None:
    try:
        return int(store.pid_path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _alive(store: RunStore) -> bool | None:
    """True/False when we know; None when the run never got a process (still being spawned)."""
    process = _processes.get(store.run_id)
    if process is not None:
        return process.poll() is None
    pid = _read_pid(store)
    return None if pid is None else _pid_alive(pid)


def _log_tail(store: RunStore, lines: int = 5) -> str:
    try:
        return "\n".join(store.log_path.read_text(errors="replace").splitlines()[-lines:])
    except FileNotFoundError:
        return ""


def _reconcile(store: RunStore, summary: RunSummary) -> RunSummary:
    """Mark a queued/running run failed when its runner process is gone."""
    if summary.status not in ACTIVE_STATUSES:
        return summary
    alive = _alive(store)
    stale_queue = alive is None and utcnow() - summary.created_at > QUEUED_GRACE
    if alive is False or stale_queue:
        tail = _log_tail(store)
        summary = summary.model_copy(
            update={
                "status": "failed",
                "finished_at": utcnow(),
                "error": "runner process exited unexpectedly" + (f": {tail}" if tail else ""),
            }
        )
        store.write_summary(summary)
        _write_progress(store, summary, "runner process exited unexpectedly")
    return summary


def _write_progress(store: RunStore, summary: RunSummary, message: str) -> None:
    store.write_progress(
        RunProgress(
            run_id=summary.run_id,
            status=summary.status,
            trials_total=summary.trials_total,
            trials_done=summary.trials_done,
            message=message,
            updated_at=utcnow(),
        )
    )


def _store(run_id: str) -> RunStore:
    if not is_safe_id(run_id):
        raise NotFoundError(run_id)
    store = RunStore(run_id)
    if not store.exists():
        raise NotFoundError(run_id)
    return store


# --- datasets and runs ---


def datasets() -> list[Dataset]:
    return list_datasets()


def list_runs() -> list[RunSummary]:
    root = runs_dir()
    if not root.exists():
        return []
    summaries: list[RunSummary] = []
    for path in root.iterdir():
        if not (path / "run.json").exists() or not is_safe_id(path.name):
            continue
        store = RunStore(path.name)
        summary = store.read_summary()
        if summary is not None:
            summaries.append(_reconcile(store, summary))
    return sorted(summaries, key=lambda s: s.created_at, reverse=True)


def active_run() -> RunSummary | None:
    return next((s for s in list_runs() if s.status in ACTIVE_STATUSES), None)


def start_run(config: RunConfig) -> RunSummary:
    with _lock:
        running = active_run()
        if running is not None:
            raise RunConflictError(f"run {running.run_id} is still {running.status}")
        try:
            summary = create_run(config)
        except DatasetError as exc:
            raise InvalidConfigError(str(exc)) from exc
        store = RunStore(summary.run_id)
        process = spawn_runner(summary.run_id)
        _processes[summary.run_id] = process
        store.pid_path.write_text(str(process.pid))
        return summary


def get_run(run_id: str) -> RunSummary:
    store = _store(run_id)
    summary = store.read_summary()
    if summary is None:
        raise NotFoundError(run_id)
    return _reconcile(store, summary)


def get_progress(run_id: str) -> RunProgress:
    summary = get_run(run_id)
    progress = RunStore(run_id).read_progress()
    if progress is None or progress.status != summary.status:
        # The summary is the source of truth for status (e.g. after a crash or cancel).
        base = progress.model_dump() if progress else {}
        progress = RunProgress(
            **{
                **base,
                "run_id": run_id,
                "status": summary.status,
                "trials_total": summary.trials_total,
                "trials_done": summary.trials_done,
                "updated_at": base.get("updated_at", utcnow()),
                "message": summary.error or base.get("message", ""),
            }
        )
    return progress


def cancel_run(run_id: str) -> None:
    store = _store(run_id)
    summary = store.read_summary()
    if summary is None or summary.status not in ACTIVE_STATUSES:
        return
    store.cancel_path.write_text("cancelled")
    process = _processes.pop(run_id, None)
    if process is not None and process.poll() is None:
        process.terminate()
    elif process is None:
        pid = _read_pid(store)
        if pid is not None and _pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    summary = summary.model_copy(update={"status": "cancelled", "finished_at": utcnow()})
    store.write_summary(summary)
    _write_progress(store, summary, "cancelled by user")


# --- trials and labels ---


def list_trials(run_id: str) -> list[TrialResult]:
    store = _store(run_id)
    return [t.model_copy(update={"transcript": []}) for t in store.list_trials()]


def get_trial(run_id: str, trial_id: str) -> TrialResult:
    store = _store(run_id)
    if not is_safe_id(trial_id):
        raise NotFoundError(trial_id)
    trial = store.read_trial(trial_id)
    if trial is None:
        raise NotFoundError(trial_id)
    return trial


def list_labels(run_id: str) -> list[HumanLabel]:
    return _store(run_id).read_labels()


def upsert_label(
    run_id: str, trial_id: str, grader: str, human_passed: bool, note: str = ""
) -> HumanLabel:
    store = _store(run_id)
    get_trial(run_id, trial_id)
    label = HumanLabel(
        trial_id=trial_id,
        grader=grader,
        human_passed=human_passed,
        note=note,
        labelled_at=utcnow(),
    )
    with _lock:
        labels = [
            item
            for item in store.read_labels()
            if not (item.trial_id == trial_id and item.grader == grader)
        ]
        labels.append(label)
        store.write_labels(labels)
    return label


def calibration() -> CalibrationStats:
    """Agreement between model-grader (judge) verdicts and human labels across all runs.
    Labels on code graders, missing trials or skipped judge verdicts are not comparable."""
    total = agree = false_pass = false_fail = 0
    per_grader: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    root = runs_dir()
    for path in sorted(root.iterdir()) if root.exists() else []:
        if not is_safe_id(path.name) or not (path / "run.json").exists():
            continue
        store = RunStore(path.name)
        for label in store.read_labels():
            trial = store.read_trial(label.trial_id)
            if trial is None:
                continue
            result = next((g for g in trial.graders if g.grader == label.grader), None)
            if result is None or result.kind != "model" or is_skipped(result):
                continue
            total += 1
            per_grader[label.grader][1] += 1
            if result.passed == label.human_passed:
                agree += 1
                per_grader[label.grader][0] += 1
            elif result.passed:
                false_pass += 1
            else:
                false_fail += 1
    return CalibrationStats(
        labels=total,
        agreement=round(agree / total, 4) if total else None,
        judge_false_pass=false_pass,
        judge_false_fail=false_fail,
        by_grader={k: round(a / n, 4) for k, (a, n) in sorted(per_grader.items()) if n},
    )


# --- live self-evaluation ---


def _judge_error(record: dict[str, Any]) -> bool:
    payload = record.get("payload") or {}
    judge = payload.get("judge") if isinstance(payload.get("judge"), dict) else {}
    return bool(payload.get("judge_error") or payload.get("error") or (judge or {}).get("error"))


def summarise_self_eval(records: list[dict[str, Any]], days: int) -> SelfEvalStats:
    evals = [r for r in records if r["kind"] == "eval"]
    stage_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in evals:
        if record.get("stage") and record.get("passed") is not None:
            stage_counts[record["stage"]][0] += int(bool(record["passed"]))
            stage_counts[record["stage"]][1] += 1
    retries = [r for r in records if r["kind"] == "recovery" and r.get("action") == "retry"]
    successes = 0
    for retry in retries:
        successes += any(
            e.get("stage") == "independent"
            and e.get("passed")
            and e["request_id"] == retry["request_id"]
            and e["subtask_id"] == retry["subtask_id"]
            and e.get("attempt", 1) >= retry.get("attempt", 2)
            for e in evals
        )
    judge_errors = sum(1 for r in evals if r.get("stage") == "independent" and _judge_error(r))
    recent = sorted(records, key=lambda r: r["created_at"], reverse=True)[:RECENT_SELF_EVAL]
    return SelfEvalStats(
        window_days=days,
        evaluations=len(evals),
        by_stage={k: round(p / n, 4) for k, (p, n) in sorted(stage_counts.items()) if n},
        retries=len(retries),
        retry_success_rate=round(successes / len(retries), 4) if retries else None,
        judge_errors=judge_errors,
        recent=[{**r, "created_at": r["created_at"].isoformat()} for r in recent],
    )


async def self_eval_stats(days: int = 7) -> SelfEvalStats:
    from app.data.repositories import platform

    records = await platform.list_eval_records(since=utcnow() - timedelta(days=days))
    return summarise_self_eval(records, days)
