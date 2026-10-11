"""Offline eval harness contracts. Frozen for Phase 3; frontend/src/types/evals.ts mirrors them.

Terminology follows "Demystifying evals for AI agents":
- task: one question with unambiguous success criteria and a reference answer
- trial: one attempt at a task (run k trials for pass@k / pass^k)
- grader: one check on a trial. code graders are deterministic; model graders use the judge;
  human labels calibrate the model graders
- transcript: every stream event of the trial, stored with it
- suite: "capability" (hill to climb, may start low) or "regression" (should stay near 100%)

Storage: files under settings.evals_dir — datasets in backend/evals/datasets/*.json (committed),
runs in <evals_dir>/runs/<run_id>/{run.json, progress.json, trials/<trial_id>.json, labels.json}.
Each run executes in a subprocess against a freshly seeded fixture database so ground truth is
stable and trials do not share state.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.judge import JudgeVerdict

Suite = Literal["capability", "regression"]
PeerExpectation = Literal["required", "forbidden", "any"]
GraderKind = Literal["code", "model", "human"]
RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class RequiredFact(BaseModel):
    """A fact the final answer must state. Passes if any alternative appears (case-insensitive,
    numbers compared after normalising separators/currency). Alternatives may be templates over
    the eval database's scenarios.json, e.g. "{scenario.over_budget.project_name}"."""

    description: str
    any_of: list[str]


class ExpectedBehaviour(BaseModel):
    clarification: bool = False  # True: the CEO must ask back and dispatch no agents
    agents_required: list[str] = []  # must appear in the plan or receive a peer request
    agents_forbidden: list[str] = []
    max_agents: int | None = None  # e.g. 1 for single-domain questions
    peer_messages: PeerExpectation = "any"
    required_facts: list[RequiredFact] = []
    forbidden_facts: list[RequiredFact] = []  # e.g. invented names; must NOT appear
    must_report_unanswered: bool = False  # e.g. data no agent owns
    reference_answer: str = ""  # used by reference-based model graders


class EvalTask(BaseModel):
    id: str  # stable, e.g. "fin-001"
    suite: Suite
    category: str  # e.g. "single-domain", "cross-domain", "a2a", "clarification", "refusal"
    question: str
    expected: ExpectedBehaviour
    graders: list[str]  # grader names from app.evals.graders registry
    tags: list[str] = []
    notes: str = ""  # why this task exists / which failure it guards against


class Dataset(BaseModel):
    name: str  # e.g. "golden"
    version: str  # bump when tasks change
    description: str
    tasks: list[EvalTask]


class GraderResult(BaseModel):
    grader: str
    kind: GraderKind
    passed: bool
    score: float = Field(ge=0.0, le=1.0)  # partial credit
    weight: float = 1.0
    reasons: list[str] = []
    judge: JudgeVerdict | None = None  # model graders only
    details: dict[str, Any] = {}


class TrialResult(BaseModel):
    trial_id: str
    run_id: str
    task_id: str
    index: int  # 0..k-1
    status: Literal["passed", "failed", "error"]
    score: float  # weighted grader score, 0..1
    passed: bool  # all required graders passed and score >= task threshold
    graders: list[GraderResult]
    question: str
    final_answer: str | None = None
    clarification: str | None = None
    agents_planned: list[str] = []
    peer_requests: int = 0
    refusals: int = 0
    recoveries: int = 0  # recovery events (live self-evaluation retries) during the trial
    duration_ms: int = 0
    llm_calls: int = 0
    error: str | None = None
    trace_url: str | None = None
    transcript: list[dict[str, Any]] = []  # serialized stream events
    started_at: datetime
    finished_at: datetime | None = None


class TaskSummary(BaseModel):
    task_id: str
    suite: Suite
    category: str
    question: str
    trials: int
    passes: int
    pass_at_k: bool  # at least one trial passed
    pass_hat_k: bool  # every trial passed
    mean_score: float
    grader_pass_rates: dict[str, float]


class RunConfig(BaseModel):
    dataset: str = "golden"
    suites: list[Suite] = ["capability", "regression"]
    task_ids: list[str] = []  # empty = all tasks in the chosen suites
    trials: int = Field(default=1, ge=1, le=5)
    judge_enabled: bool = True
    self_eval_recovery: Literal["retry", "observe"] = "retry"


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    config: RunConfig
    dataset_version: str
    agent_model: str
    ceo_model: str
    judge_model: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tasks_total: int = 0
    trials_total: int = 0
    trials_done: int = 0
    pass_rate: float | None = None  # passed trials / trials
    pass_at_k: float | None = None  # share of tasks with >=1 passing trial
    pass_hat_k: float | None = None  # share of tasks where every trial passed
    mean_score: float | None = None
    by_suite: dict[str, float] = {}  # suite -> pass rate
    by_category: dict[str, float] = {}
    grader_pass_rates: dict[str, float] = {}
    tasks: list[TaskSummary] = []
    error: str | None = None


class RunProgress(BaseModel):
    run_id: str
    status: RunStatus
    trials_total: int
    trials_done: int
    current_task: str | None = None
    message: str = ""
    updated_at: datetime


class HumanLabel(BaseModel):
    """A human verdict on one model grader of one trial, used to calibrate the judge."""

    trial_id: str
    grader: str
    human_passed: bool
    note: str = ""
    labelled_at: datetime


class CalibrationStats(BaseModel):
    labels: int
    agreement: float | None  # share of labels where judge verdict == human verdict
    judge_false_pass: int  # judge passed, human failed
    judge_false_fail: int  # judge failed, human passed
    by_grader: dict[str, float] = {}


class SelfEvalStats(BaseModel):
    """Live self-evaluation across real chat requests (from the Langfuse/events record)."""

    window_days: int
    evaluations: int
    by_stage: dict[str, float]  # stage -> pass rate
    retries: int
    retry_success_rate: float | None
    judge_errors: int
    recent: list[dict[str, Any]] = []  # recent eval_result / recovery records for the feed
