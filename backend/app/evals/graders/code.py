"""Deterministic code graders. They grade outcomes (who was involved, what the answer states, what
evidence backs it), not the exact path the agents took."""

import re

from app.evals.contracts import GraderResult
from app.evals.graders.base import Grader, GradingContext
from app.evals.matching import find_fact, normalise_text

DEFAULT_LLM_BUDGET = 25
DEFAULT_SECONDS_BUDGET = 300
ALLOW_FAILURE_TAG = "allow-agent-failure"
UNANSWERED_PHRASES = (
    "could not",
    "couldn't",
    "cannot",
    "can't",
    "unable",
    "not available",
    "unavailable",
    "no data",
    "don't have",
    "do not have",
    "does not have",
    "doesn't have",
    "not own",
    "doesn't own",
    "does not own",
    "no agent",
    "none of the",
    "outside",
    "not tracked",
    "isn't tracked",
    "not track",
    "not part of",
    "no record",
    "not found",
    "no information",
    "not covered",
    "no such",
    "not possible",
    "not recorded",
    "unanswered",
)


class RoutingGrader(Grader):
    """Required agents involved, forbidden agents not involved, and at most max_agents involved.
    Involved = assigned a subtask in the plan, or received a delivered peer request."""

    name = "routing"

    async def grade(self, ctx: GradingContext) -> GraderResult:
        expected, trial = ctx.task.expected, ctx.trial
        involved = set(trial.involved_agents)
        checks: list[tuple[bool, str]] = []
        for agent in expected.agents_required:
            checks.append((agent in involved, f"required agent {agent!r} involved"))
        for agent in expected.agents_forbidden:
            checks.append((agent not in involved, f"forbidden agent {agent!r} not involved"))
        if expected.max_agents is not None:
            checks.append(
                (
                    len(involved) <= expected.max_agents,
                    f"at most {expected.max_agents} agent(s) involved (got {len(involved)})",
                )
            )
        details = {
            "planned": trial.planned_agents,
            "peer_recipients": trial.peer_recipients,
            "involved": sorted(involved),
        }
        if not checks:
            return self.result(1.0, ["no routing expectations"], details=details)
        passed = [c for c in checks if c[0]]
        reasons = [("ok: " if ok else "FAIL: ") + text for ok, text in checks]
        return self.result(len(passed) / len(checks), reasons, details=details)


class ClarificationGrader(Grader):
    """clarification=True: the CEO asked back and dispatched nothing.
    clarification=False: the CEO did not ask back and produced a final answer."""

    name = "clarification"

    async def grade(self, ctx: GradingContext) -> GraderResult:
        trial = ctx.trial
        asked = trial.clarification is not None and trial.final is None
        dispatched = bool(trial.agents_started) or trial.subtask_count > 0
        details = {"asked": asked, "dispatched": dispatched, "question": trial.clarification}
        if ctx.task.expected.clarification:
            checks = [
                (asked, "asked a clarifying question"),
                (not dispatched, "dispatched no agents"),
            ]
        else:
            checks = [
                (not asked, "did not ask for clarification"),
                (trial.final is not None, "produced a final answer"),
            ]
        reasons = [("ok: " if ok else "FAIL: ") + text for ok, text in checks]
        return self.result(sum(ok for ok, _ in checks) / len(checks), reasons, details=details)


class PeerExpectationGrader(Grader):
    """required: at least one delivered peer request. forbidden: no peer request attempted.
    any: always passes (reported for information)."""

    name = "peer_expectation"
    weight = 0.5

    async def grade(self, ctx: GradingContext) -> GraderResult:
        expectation = ctx.task.expected.peer_messages
        trial = ctx.trial
        pairs = sorted(
            {f"{e['message']['sender']}->{e['message']['recipient']}" for e in trial.peer_requests}
        )
        details = {
            "expectation": expectation,
            "delivered": len(trial.peer_requests),
            "attempted": len(trial.attempted_peer_requests),
            "refused": len(trial.refusals),
            "pairs": pairs,
        }
        if expectation == "required":
            ok = bool(trial.peer_requests)
            reason = f"{len(trial.peer_requests)} peer request(s) delivered {pairs}"
        elif expectation == "forbidden":
            ok = not trial.attempted_peer_requests
            reason = f"{len(trial.attempted_peer_requests)} peer request(s) attempted {pairs}"
        else:
            ok, reason = True, f"no expectation; {len(trial.peer_requests)} delivered {pairs}"
        return self.result(
            1.0 if ok else 0.0, [("ok: " if ok else "FAIL: ") + reason], details=details
        )


class RequiredFactsGrader(Grader):
    """Partial credit = fraction of required facts stated in the final answer."""

    name = "required_facts"
    weight = 2.0

    async def grade(self, ctx: GradingContext) -> GraderResult:
        facts = ctx.task.expected.required_facts
        if not facts:
            return self.result(1.0, ["no required facts"])
        text = ctx.trial.answer_text
        found: dict[str, str | None] = {f.description: find_fact(text, f.any_of) for f in facts}
        reasons = [
            f"ok: {desc} ({hit!r})" if hit else f"FAIL: missing {desc} (any of {fact.any_of})"
            for (desc, hit), fact in zip(found.items(), facts, strict=True)
        ]
        score = sum(hit is not None for hit in found.values()) / len(facts)
        return self.result(score, reasons, details={"found": found})


class ForbiddenFactsGrader(Grader):
    """Fails when the final answer states something it must not (e.g. an invented name)."""

    name = "forbidden_facts"

    async def grade(self, ctx: GradingContext) -> GraderResult:
        facts = ctx.task.expected.forbidden_facts
        if not facts:
            return self.result(1.0, ["no forbidden facts"])
        text = ctx.trial.answer_text
        hits = {f.description: find_fact(text, f.any_of) for f in facts}
        reasons = [
            f"FAIL: states {desc} ({hit!r})" if hit else f"ok: does not state {desc}"
            for desc, hit in hits.items()
        ]
        score = 1 - sum(hit is not None for hit in hits.values()) / len(facts)
        return self.result(score, reasons, details={"hits": hits})


class EvidenceValidGrader(Grader):
    """Every evidence_ref cited by a final-answer claim exists among the trial's agent evidence,
    and every claim cites at least one ref."""

    name = "evidence_valid"

    async def grade(self, ctx: GradingContext) -> GraderResult:
        trial = ctx.trial
        if trial.final is None:
            if ctx.task.expected.clarification:
                return self.result(1.0, ["no final answer expected"])
            return self.result(0.0, ["FAIL: no final answer"])
        claims = trial.claims
        known = trial.evidence_refs
        if not claims:
            if ctx.task.expected.must_report_unanswered:
                return self.result(1.0, ["no claims; acceptable for an unanswerable question"])
            return self.result(0.0, ["FAIL: the final answer has no evidence-backed claims"])
        cited = [ref for claim in claims for ref in claim.get("evidence_refs", [])]
        invalid = sorted({ref for ref in cited if ref not in known})
        uncited = [claim.get("text", "")[:80] for claim in claims if not claim.get("evidence_refs")]
        good_claims = sum(
            1
            for claim in claims
            if claim.get("evidence_refs") and all(r in known for r in claim["evidence_refs"])
        )
        reasons = [f"{good_claims}/{len(claims)} claims fully backed by trial evidence"]
        reasons += [f"FAIL: unknown evidence ref {ref!r}" for ref in invalid]
        reasons += [f"FAIL: claim without evidence: {text!r}" for text in uncited]
        return self.result(
            good_claims / len(claims),
            reasons,
            details={"claims": len(claims), "cited": len(cited), "invalid": invalid},
        )


class UnansweredReportedGrader(Grader):
    """For questions the system cannot answer: the answer says so plainly (an `unanswered` entry,
    a clarifying question, or explicit wording) instead of inventing an answer."""

    name = "unanswered_reported"

    async def grade(self, ctx: GradingContext) -> GraderResult:
        trial = ctx.trial
        if not ctx.task.expected.must_report_unanswered:
            return self.result(1.0, ["not applicable: the task is answerable"])
        if trial.unanswered:
            return self.result(1.0, [f"ok: unanswered entries: {trial.unanswered[:3]}"])
        if trial.clarification and trial.final is None:
            return self.result(1.0, ["ok: asked back instead of answering"])
        text = normalise_text(trial.answer_text)
        phrase = next((p for p in UNANSWERED_PHRASES if p in text), None)
        if phrase:
            return self.result(1.0, [f"ok: answer states the gap ({phrase!r})"])
        return self.result(
            0.0, ["FAIL: the answer does not say the question could not be answered"]
        )


class NoErrorsGrader(Grader):
    """No error event and no failed agent result (unless the task is tagged allow-agent-failure)."""

    name = "no_errors"

    async def grade(self, ctx: GradingContext) -> GraderResult:
        trial = ctx.trial
        errors = [e.get("message", "") for e in trial.errors]
        failed = [
            f"{r.get('agent')}:{r.get('subtask_id')}: {r.get('error')}"
            for r in trial.failed_results
        ]
        if ALLOW_FAILURE_TAG in ctx.task.tags:
            failed = []
        problems = [f"FAIL: error event: {m}" for m in errors] + [
            f"FAIL: failed agent result {f}" for f in failed
        ]
        if not trial.final and not trial.clarification:
            problems.append("FAIL: the request ended without an answer or a clarification")
        if not problems:
            return self.result(1.0, ["ok: no errors"])
        return self.result(0.0, problems, details={"errors": errors, "failed": failed})


def _budget(tags: list[str], key: str, default: int) -> int:
    for tag in tags:
        match = re.fullmatch(rf"budget:{key}=(\d+)", tag)
        if match:
            return int(match.group(1))
    return default


class EfficiencyGrader(Grader):
    """LLM calls and wall time against a budget (tags budget:llm=N, budget:seconds=N).
    Informational and low weight: slow is reported, never failed."""

    name = "efficiency"
    weight = 0.25
    informational = True

    async def grade(self, ctx: GradingContext) -> GraderResult:
        trial = ctx.trial
        llm_budget = _budget(ctx.task.tags, "llm", DEFAULT_LLM_BUDGET)
        seconds_budget = _budget(ctx.task.tags, "seconds", DEFAULT_SECONDS_BUDGET)
        seconds = trial.duration_ms / 1000
        llm_score = min(1.0, llm_budget / trial.llm_calls) if trial.llm_calls else 1.0
        time_score = min(1.0, seconds_budget / seconds) if seconds else 1.0
        reasons = [
            f"{trial.llm_calls} LLM calls (budget {llm_budget})",
            f"{seconds:.1f}s (budget {seconds_budget}s)",
        ]
        return self.result(
            (llm_score + time_score) / 2,
            reasons,
            details={"llm_calls": trial.llm_calls, "seconds": round(seconds, 1)},
        )


CODE_GRADERS: list[type[Grader]] = [
    RoutingGrader,
    ClarificationGrader,
    PeerExpectationGrader,
    RequiredFactsGrader,
    ForbiddenFactsGrader,
    EvidenceValidGrader,
    UnansweredReportedGrader,
    NoErrorsGrader,
    EfficiencyGrader,
]
