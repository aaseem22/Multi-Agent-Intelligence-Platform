# Evals API (Phase 3 contract)

Types: `app/evals/contracts.py` and `app/core/judge.py`, mirrored in `frontend/src/types/evals.ts`.
All routes live under `/api/evals` and stay thin: they call `app.evals.service`.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/evals/datasets` | | `Dataset[]` |
| GET | `/api/evals/runs` | | `RunSummary[]`, newest first |
| POST | `/api/evals/runs` | `RunConfig` | `RunSummary` (status `queued`); spawns the runner subprocess |
| GET | `/api/evals/runs/{run_id}` | | `RunSummary` |
| GET | `/api/evals/runs/{run_id}/progress` | | `RunProgress` (poll every 2–3 s while running) |
| POST | `/api/evals/runs/{run_id}/cancel` | | 204 |
| GET | `/api/evals/runs/{run_id}/trials` | | `TrialResult[]` with `transcript: []` |
| GET | `/api/evals/runs/{run_id}/trials/{trial_id}` | | `TrialResult` including `transcript` |
| GET | `/api/evals/runs/{run_id}/labels` | | `HumanLabel[]` |
| POST | `/api/evals/runs/{run_id}/labels` | `HumanLabelRequest` | `HumanLabel` (upsert by trial_id + grader) |
| GET | `/api/evals/calibration` | | `CalibrationStats` across all runs |
| GET | `/api/evals/self-eval?days=7` | | `SelfEvalStats` from the `eval_records` table |

Errors: 404 for unknown run/trial ids, 409 when starting a run while another is running
(one run at a time: the Gemini free tier cannot sustain two), 422 for invalid config.

Runner CLI (also what POST /runs spawns):

    uv run python -m app.evals.run --dataset golden --trials 1 [--suite regression] [--task fin-001]

Each run seeds a fresh fixture database at `<evals_dir>/runs/<run_id>/org.db` (offline GitHub
fixtures, fixed SEED) so ground truth matches `scenarios.json` written into the same folder.
