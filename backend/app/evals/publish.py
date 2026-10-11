"""Publish completed local eval runs into the repo, and sync them into a deployment's volume.

    uv run python -m app.evals.publish --all          # every completed local run
    uv run python -m app.evals.publish <run_id> ...   # chosen runs
    uv run python -m app.evals.publish --list         # what is published
    uv run python -m app.evals.publish --sync         # deployment boot: copy published runs in

Published runs live in backend/evals/published/<run_id>/ (committed). Only results are copied:
config, summary, progress, scenarios, trials (with transcripts) and human labels — never the
run's scratch database or process files. Syncing copies a published run into
<evals_dir>/runs only when the deployment does not have it yet, so labels added on the
deployed site are never overwritten.
"""

import argparse
import shutil
import sys
from pathlib import Path

from app.core.config import BACKEND_DIR
from app.evals.storage import is_safe_id, read_json, runs_dir

PUBLISHED_DIR = BACKEND_DIR / "evals" / "published"
RESULT_FILES = ("config.json", "run.json", "progress.json", "scenarios.json", "labels.json")


def _completed(run_dir: Path) -> bool:
    summary = run_dir / "run.json"
    return summary.exists() and read_json(summary).get("status") == "completed"


def publish(
    run_ids: list[str], *, source: Path | None = None, target: Path | None = None
) -> list[str]:
    """Copy completed runs' results into the published folder; returns the ids published."""
    source, target = source or runs_dir(), target or PUBLISHED_DIR
    published = []
    for run_id in run_ids:
        run_dir = source / run_id
        if not is_safe_id(run_id) or not run_dir.is_dir():
            print(f"skip {run_id}: no such run", file=sys.stderr)
            continue
        if not _completed(run_dir):
            print(f"skip {run_id}: not completed", file=sys.stderr)
            continue
        destination = target / run_id
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        for name in RESULT_FILES:
            if (run_dir / name).exists():
                shutil.copy2(run_dir / name, destination / name)
        if (run_dir / "trials").is_dir():
            shutil.copytree(run_dir / "trials", destination / "trials")
        published.append(run_id)
    return published


def completed_runs(source: Path | None = None) -> list[str]:
    source = source or runs_dir()
    if not source.is_dir():
        return []
    return sorted(p.name for p in source.iterdir() if p.is_dir() and _completed(p))


def sync_published(*, source: Path | None = None, target: Path | None = None) -> list[str]:
    """Copy published runs the deployment does not have yet; returns the ids copied."""
    source, target = source or PUBLISHED_DIR, target or runs_dir()
    if not source.is_dir():
        return []
    copied = []
    for run_dir in sorted(p for p in source.iterdir() if p.is_dir() and is_safe_id(p.name)):
        destination = target / run_dir.name
        if destination.exists():
            continue
        shutil.copytree(run_dir, destination)
        copied.append(run_dir.name)
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish or sync eval run results")
    parser.add_argument("run_ids", nargs="*", help="run ids to publish")
    parser.add_argument("--all", action="store_true", help="publish every completed local run")
    parser.add_argument("--list", action="store_true", help="list published runs")
    parser.add_argument("--sync", action="store_true", help="copy published runs into evals_dir")
    args = parser.parse_args()

    if args.sync:
        copied = sync_published()
        print(f"Synced {len(copied)} published eval run(s): {', '.join(copied) or 'none new'}")
        return
    if args.list:
        names = sorted(p.name for p in PUBLISHED_DIR.iterdir()) if PUBLISHED_DIR.is_dir() else []
        print("\n".join(names) or "No published runs")
        return
    run_ids = completed_runs() if args.all else args.run_ids
    if not run_ids:
        parser.error("give run ids or --all")
    done = publish(run_ids)
    print(f"Published {len(done)} run(s) to {PUBLISHED_DIR}: {', '.join(done) or 'none'}")
    if done:
        print("Commit backend/evals/published/ and push to show them on the deployed site.")


if __name__ == "__main__":
    main()
