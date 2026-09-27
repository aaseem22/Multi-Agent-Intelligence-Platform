"""CEO synthesiser: combines AgentResults into one FinalAnswer. Evidence references are checked
against the results, failures are always reported, and it never raises."""

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.ceo.prompts import SYNTHESIS_SYSTEM_PROMPT, synthesis_user_prompt
from app.core.contracts import AgentResult, Claim, FinalAnswer, Subtask
from app.core.llm import get_llm, with_llm_retries

logger = logging.getLogger(__name__)

NO_RESULTS_ANSWER = "No agent returned a result, so the question could not be answered."


async def synthesise(
    question: str, subtasks: list[Subtask], results: list[AgentResult]
) -> FinalAnswer:
    try:
        raw = await _call_llm(question, subtasks, results)
        return enforce_rules(raw, subtasks, results)
    except Exception as exc:
        logger.warning("Synthesis failed, using deterministic fallback: %s", exc)
        return fallback_answer(subtasks, results)


async def _call_llm(
    question: str, subtasks: list[Subtask], results: list[AgentResult]
) -> FinalAnswer:
    llm = get_llm("ceo").with_structured_output(FinalAnswer)
    messages = [
        SystemMessage(SYNTHESIS_SYSTEM_PROMPT),
        HumanMessage(synthesis_user_prompt(question, subtasks, results)),
    ]
    raw = await with_llm_retries(lambda: llm.ainvoke(messages))
    if isinstance(raw, dict):
        return FinalAnswer.model_validate(raw)
    if not isinstance(raw, FinalAnswer):
        raise TypeError(f"Synthesis returned {type(raw).__name__}, expected FinalAnswer")
    return raw


def enforce_rules(
    raw: FinalAnswer, subtasks: list[Subtask], results: list[AgentResult]
) -> FinalAnswer:
    """Strip evidence refs not present in the results and add any missing failure reports."""
    claims = _valid_claims(raw.claims, results)
    unanswered = [u for u in raw.unanswered if u.strip()]
    added = _missing_failures(unanswered, subtasks, results)
    answer = raw.answer.strip() or NO_RESULTS_ANSWER
    if added:
        answer += "\n\nCould not be answered: " + " ".join(added)
    return FinalAnswer(answer=answer, claims=claims, unanswered=unanswered + added)


def fallback_answer(subtasks: list[Subtask], results: list[AgentResult]) -> FinalAnswer:
    """Deterministic answer built straight from the results when the LLM is unavailable."""
    answered = [r for r in results if r.status in ("ok", "partial") and r.answer.strip()]
    claims = [
        Claim(
            text=r.answer.strip(),
            evidence_refs=list(dict.fromkeys(e.source_ref for e in r.evidence)),
            agents=[r.agent],
        )
        for r in answered
        if r.evidence
    ]
    unanswered = _missing_failures([], subtasks, results)
    if answered:
        answer = "\n\n".join(f"{r.agent}: {r.answer.strip()}" for r in answered)
    else:
        answer = NO_RESULTS_ANSWER
    if unanswered:
        answer += "\n\nCould not be answered: " + " ".join(unanswered)
    return FinalAnswer(answer=answer, claims=claims, unanswered=unanswered)


def _valid_claims(claims: list[Claim], results: list[AgentResult]) -> list[Claim]:
    ref_agents: dict[str, list[str]] = {}
    for result in results:
        for evidence in result.evidence:
            ref_agents.setdefault(evidence.source_ref, [])
            if result.agent not in ref_agents[evidence.source_ref]:
                ref_agents[evidence.source_ref].append(result.agent)
    valid = []
    for claim in claims:
        refs = [ref for ref in dict.fromkeys(claim.evidence_refs) if ref in ref_agents]
        stripped = set(claim.evidence_refs) - set(refs)
        if stripped:
            logger.warning("Stripped unknown evidence refs from claim: %s", sorted(stripped))
        if not refs:
            logger.warning("Dropped claim with no valid evidence: %s", claim.text)
            continue
        agents = list(dict.fromkeys(a for ref in refs for a in ref_agents[ref]))
        valid.append(Claim(text=claim.text, evidence_refs=refs, agents=agents))
    return valid


def _describe_failure(result: AgentResult) -> str:
    reason = result.error or result.answer.strip() or "no reason given"
    labels = {
        "failed": "failed",
        "partial": "only partly answered",
        "needs_clarification": "needs clarification",
    }
    return (
        f"Agent '{result.agent}' {labels[result.status]} on subtask {result.subtask_id}: {reason}"
    )


def _missing_failures(
    existing: list[str], subtasks: list[Subtask], results: list[AgentResult]
) -> list[str]:
    """Failure reports for non-ok results and missing results that `existing` does not cover."""
    mentioned = " ".join(existing)
    added = []
    for result in results:
        if result.status != "ok" and not _mentions(mentioned, result.agent):
            added.append(_describe_failure(result))
    returned = {r.subtask_id for r in results}
    for subtask in subtasks:
        if subtask.id not in returned and not _mentions(mentioned, subtask.assigned_to):
            added.append(
                f"Agent '{subtask.assigned_to}' returned no result for subtask {subtask.id}: "
                f"{subtask.instruction}"
            )
    return added


def _mentions(text: str, agent: str) -> bool:
    return re.search(rf"\b{re.escape(agent)}\b", text, re.IGNORECASE) is not None
