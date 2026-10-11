"""File storage for eval runs: <evals_dir>/runs/<run_id>/{config.json, run.json, progress.json,
trials/<trial_id>.json, labels.json, runner.log, pid}. Writes are atomic (temp file + rename) so
the API never reads a half-written file while the runner subprocess is writing."""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter

from app.core.config import BACKEND_DIR, get_settings
from app.evals.contracts import HumanLabel, RunConfig, RunProgress, RunSummary, TrialResult

M = TypeVar("M", bound=BaseModel)

SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
DATASETS_DIR = BACKEND_DIR / "evals" / "datasets"
_labels_adapter = TypeAdapter(list[HumanLabel])


def is_safe_id(value: str) -> bool:
    return bool(SAFE_ID.match(value)) and ".." not in value


def evals_dir() -> Path:
    path = Path(get_settings().evals_dir)
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    return path


def runs_dir() -> Path:
    return evals_dir() / "runs"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, default=str)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_model(path: Path, model: BaseModel) -> None:
    write_json(path, model.model_dump(mode="json"))


def read_model(path: Path, cls: type[M]) -> M | None:
    if not path.exists():
        return None
    return cls.model_validate(read_json(path))


class RunStore:
    """All files of one run."""

    def __init__(self, run_id: str, root: Path | None = None) -> None:
        if not is_safe_id(run_id):
            raise ValueError(f"invalid run id {run_id!r}")
        self.run_id = run_id
        self.dir = (root or runs_dir()) / run_id

    @property
    def db_path(self) -> Path:
        return self.dir / "org.db"

    @property
    def scenarios_path(self) -> Path:
        return self.dir / "scenarios.json"

    @property
    def trials_dir(self) -> Path:
        return self.dir / "trials"

    @property
    def log_path(self) -> Path:
        return self.dir / "runner.log"

    @property
    def pid_path(self) -> Path:
        return self.dir / "pid"

    @property
    def cancel_path(self) -> Path:
        return self.dir / "cancel"

    def exists(self) -> bool:
        return (self.dir / "run.json").exists()

    # config / summary / progress
    def write_config(self, config: RunConfig) -> None:
        write_model(self.dir / "config.json", config)

    def read_config(self) -> RunConfig:
        config = read_model(self.dir / "config.json", RunConfig)
        if config is None:
            raise FileNotFoundError(f"run {self.run_id} has no config.json")
        return config

    def write_summary(self, summary: RunSummary) -> None:
        write_model(self.dir / "run.json", summary)

    def read_summary(self) -> RunSummary | None:
        return read_model(self.dir / "run.json", RunSummary)

    def write_progress(self, progress: RunProgress) -> None:
        write_model(self.dir / "progress.json", progress)

    def read_progress(self) -> RunProgress | None:
        return read_model(self.dir / "progress.json", RunProgress)

    # trials
    def trial_path(self, trial_id: str) -> Path:
        if not is_safe_id(trial_id):
            raise ValueError(f"invalid trial id {trial_id!r}")
        return self.trials_dir / f"{trial_id}.json"

    def write_trial(self, trial: TrialResult) -> None:
        write_model(self.trial_path(trial.trial_id), trial)

    def read_trial(self, trial_id: str) -> TrialResult | None:
        return read_model(self.trial_path(trial_id), TrialResult)

    def list_trials(self) -> list[TrialResult]:
        if not self.trials_dir.exists():
            return []
        trials = [TrialResult.model_validate(read_json(p)) for p in self.trials_dir.glob("*.json")]
        return sorted(trials, key=lambda t: (t.started_at, t.task_id, t.index))

    # labels
    def read_labels(self) -> list[HumanLabel]:
        path = self.dir / "labels.json"
        return _labels_adapter.validate_python(read_json(path)) if path.exists() else []

    def write_labels(self, labels: list[HumanLabel]) -> None:
        write_json(self.dir / "labels.json", _labels_adapter.dump_python(labels, mode="json"))
