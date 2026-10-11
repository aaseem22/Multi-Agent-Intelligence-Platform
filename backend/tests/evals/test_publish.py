"""Publishing local eval runs into the repo and syncing them into a deployment."""

import json

from app.evals.publish import completed_runs, publish, sync_published


def _run(root, run_id, status="completed"):
    run = root / run_id
    (run / "trials").mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"run_id": run_id, "status": status}))
    (run / "config.json").write_text("{}")
    (run / "labels.json").write_text("[]")
    (run / "trials" / "t__0.json").write_text("{}")
    (run / "org.db").write_bytes(b"scratch")
    (run / "pid").write_text("123")
    return run


def test_publish_copies_results_only(tmp_path):
    local, published = tmp_path / "runs", tmp_path / "published"
    _run(local, "r1")
    _run(local, "r2", status="running")
    assert completed_runs(local) == ["r1"]
    assert publish(["r1", "r2", "missing"], source=local, target=published) == ["r1"]
    files = {p.relative_to(published / "r1").as_posix() for p in (published / "r1").rglob("*")}
    assert files == {"run.json", "config.json", "labels.json", "trials", "trials/t__0.json"}


def test_sync_adds_missing_runs_and_keeps_existing(tmp_path):
    published, deployed = tmp_path / "published", tmp_path / "deployed"
    _run(published, "r1")
    _run(published, "r2")
    existing = deployed / "r2"
    existing.mkdir(parents=True)
    (existing / "labels.json").write_text('[{"trial_id": "t__0"}]')  # labelled on the site
    assert sync_published(source=published, target=deployed) == ["r1"]
    assert (deployed / "r1" / "trials" / "t__0.json").exists()
    assert json.loads((existing / "labels.json").read_text()) == [{"trial_id": "t__0"}]
    assert sync_published(source=published, target=deployed) == []
