"""Golden datasets: backend/evals/datasets/<name>.json, validated against the Dataset model."""

from pathlib import Path

from app.evals.contracts import Dataset, EvalTask, RunConfig
from app.evals.storage import DATASETS_DIR, is_safe_id, read_json


class DatasetError(ValueError):
    pass


def _dir(datasets_dir: Path | None) -> Path:
    return datasets_dir or DATASETS_DIR


def list_datasets(datasets_dir: Path | None = None) -> list[Dataset]:
    root = _dir(datasets_dir)
    if not root.exists():
        return []
    return [Dataset.model_validate(read_json(p)) for p in sorted(root.glob("*.json"))]


def load_dataset(name: str, datasets_dir: Path | None = None) -> Dataset:
    if not is_safe_id(name):
        raise DatasetError(f"invalid dataset name {name!r}")
    path = _dir(datasets_dir) / f"{name}.json"
    if not path.exists():
        raise DatasetError(f"unknown dataset {name!r}")
    dataset = Dataset.model_validate(read_json(path))
    check_dataset(dataset)
    return dataset


def check_dataset(dataset: Dataset) -> None:
    """Structural checks the Pydantic model cannot express."""
    from app.evals.graders import GRADERS

    ids = [t.id for t in dataset.tasks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise DatasetError(f"duplicate task ids: {sorted(duplicates)}")
    for task in dataset.tasks:
        unknown = [g for g in task.graders if g not in GRADERS]
        if unknown:
            raise DatasetError(f"task {task.id}: unknown graders {unknown}")
        if not task.graders:
            raise DatasetError(f"task {task.id}: no graders")


def select_tasks(dataset: Dataset, config: RunConfig) -> list[EvalTask]:
    """Explicit task_ids win over the suite filter; otherwise every task in the chosen suites."""
    if config.task_ids:
        known = {t.id for t in dataset.tasks}
        missing = [i for i in config.task_ids if i not in known]
        if missing:
            raise DatasetError(f"unknown task ids: {missing}")
        wanted = set(config.task_ids)
        tasks = [t for t in dataset.tasks if t.id in wanted]
    else:
        tasks = [t for t in dataset.tasks if t.suite in config.suites]
    if not tasks:
        raise DatasetError("the selection contains no tasks")
    return tasks
