"""Eval runner CLI (also what POST /api/evals/runs spawns as a subprocess).

    uv run python -m app.evals.run --dataset golden --trials 1 [--suite regression] [--task fin-001]
    uv run python -m app.evals.run --run-id <id>        # execute a run created by the API
    uv run python -m app.evals.run --validate           # grade reference answers; no LLM

The Gemini free tier allows roughly 13 requests per minute, so trials run sequentially and the
estimated duration is printed before the first trial.
"""

import argparse
import asyncio
import logging
import os
import sys

from app.core.config import get_settings
from app.core.context import configure_logging
from app.evals.contracts import RunConfig
from app.evals.datasets import DatasetError, load_dataset
from app.evals.runner import create_run, execute_run
from app.evals.storage import RunStore
from app.evals.validate import validate_dataset


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the offline eval harness")
    parser.add_argument("--run-id", help="execute an existing queued run")
    parser.add_argument("--dataset", default="golden")
    parser.add_argument("--trials", type=int, default=1, help="trials per task (k), 1-5")
    parser.add_argument("--suite", action="append", choices=["capability", "regression"])
    parser.add_argument("--task", action="append", help="task id (repeatable)")
    parser.add_argument("--no-judge", action="store_true", help="skip model graders")
    parser.add_argument("--recovery", choices=["retry", "observe"], default="retry")
    parser.add_argument("--validate", action="store_true", help="validate reference answers")
    return parser.parse_args(argv)


async def validate(dataset_name: str) -> int:
    dataset = load_dataset(dataset_name)
    results = await validate_dataset(dataset)
    passed = sum(r.passed for r in results)
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        print(f"{mark} {result.task_id}: {result.resolved_question}")
        for problem in result.problems:
            print(f"     - {problem}")
    print(f"\n{passed}/{len(results)} tasks valid ({passed / len(results):.0%})")
    return 0 if passed == len(results) else 1


async def run(args: argparse.Namespace) -> int:
    if args.run_id:
        run_id = args.run_id
    else:
        config = RunConfig(
            dataset=args.dataset,
            suites=args.suite or ["capability", "regression"],
            task_ids=args.task or [],
            trials=args.trials,
            judge_enabled=not args.no_judge,
            self_eval_recovery=args.recovery,
        )
        run_id = create_run(config).run_id
    store = RunStore(run_id)
    store.pid_path.write_text(str(os.getpid()))
    summary = await execute_run(run_id)
    print(f"Results: {store.dir}")
    return 0 if summary.status == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(get_settings().log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        # One event loop for the whole run: Gemini async clients are bound to their loop.
        return asyncio.run(validate(args.dataset) if args.validate else run(args))
    except DatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
