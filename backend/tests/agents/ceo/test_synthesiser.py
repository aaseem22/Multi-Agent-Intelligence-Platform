from app.agents.ceo.supervisor import CEOAgent
from app.core.contracts import AgentResult, Claim, Evidence, FinalAnswer, Subtask

QUESTION = "Which projects are behind schedule, and is the cause people or budget?"
SUBTASKS = [
    Subtask(id="t1", assigned_to="delivery", instruction="find late projects"),
    Subtask(id="t2", assigned_to="people", instruction="check staffing"),
    Subtask(id="t3", assigned_to="ledger", instruction="check budget vs actual"),
]


def ev(ref: str) -> Evidence:
    return Evidence(source_type="db", source_ref=ref, summary=f"row {ref}")


def result(agent: str, sid: str, status: str = "ok", refs=(), error=None) -> AgentResult:
    return AgentResult(
        agent=agent,
        subtask_id=sid,
        status=status,
        answer=f"{agent} answer" if status != "failed" else "",
        evidence=[ev(r) for r in refs],
        peer_messages=[],
        error=error,
    )


def ok_results() -> list[AgentResult]:
    return [
        result("delivery", "t1", refs=["projects:id=3"]),
        result("people", "t2", refs=["allocations:id=7", "leave:id=2"]),
        result("ledger", "t3", refs=["budgets:id=9"]),
    ]


async def test_valid_claims_keep_refs_and_get_agents(scripted_llm):
    scripted_llm(
        FinalAnswer(
            answer="Project 3 is late because of staffing.",
            claims=[Claim(text="Project 3 is late", evidence_refs=["projects:id=3"])],
        )
    )
    final = await CEOAgent().synthesise(QUESTION, SUBTASKS, ok_results())
    assert final.claims[0].evidence_refs == ["projects:id=3"]
    assert final.claims[0].agents == ["delivery"]
    assert final.unanswered == []


async def test_hallucinated_evidence_refs_are_stripped(scripted_llm):
    scripted_llm(
        FinalAnswer(
            answer="...",
            claims=[
                Claim(text="late", evidence_refs=["projects:id=3", "projects:id=999"]),
                Claim(text="invented", evidence_refs=["expenses:id=1"]),
                Claim(text="no refs at all"),
            ],
        )
    )
    final = await CEOAgent().synthesise(QUESTION, SUBTASKS, ok_results())
    assert [c.text for c in final.claims] == ["late"]
    assert final.claims[0].evidence_refs == ["projects:id=3"]
    valid = {e.source_ref for r in ok_results() for e in r.evidence}
    assert all(ref in valid for c in final.claims for ref in c.evidence_refs)


async def test_synthesis_reports_failed_agent_when_llm_omits_it(scripted_llm):
    results = ok_results()
    results[2] = result("ledger", "t3", status="failed", error="LLM retries exhausted")
    scripted_llm(
        FinalAnswer(
            answer="Project 3 is late due to staffing.",
            claims=[Claim(text="late", evidence_refs=["projects:id=3"])],
        )
    )
    final = await CEOAgent().synthesise(QUESTION, SUBTASKS, results)
    assert len(final.unanswered) == 1
    assert "ledger" in final.unanswered[0] and "LLM retries exhausted" in final.unanswered[0]
    assert "failed" in final.unanswered[0]
    assert "ledger" in final.answer


async def test_synthesis_keeps_llm_failure_report_without_duplicating(scripted_llm):
    results = ok_results()
    results[1] = result("people", "t2", status="needs_clarification")
    scripted_llm(
        FinalAnswer(answer="...", unanswered=["The people agent needed clarification on t2."])
    )
    final = await CEOAgent().synthesise(QUESTION, SUBTASKS, results)
    assert final.unanswered == ["The people agent needed clarification on t2."]


async def test_partial_and_missing_results_are_reported(scripted_llm):
    results = [
        result("delivery", "t1", status="partial", refs=["projects:id=3"]),
        result("people", "t2", refs=["allocations:id=7"]),
    ]
    scripted_llm(FinalAnswer(answer="Partial picture."))
    final = await CEOAgent().synthesise(QUESTION, SUBTASKS, results)
    joined = " ".join(final.unanswered)
    assert "delivery" in joined and "partly" in joined
    assert "ledger" in joined and "no result" in joined


async def test_llm_failure_returns_deterministic_fallback(scripted_llm):
    results = ok_results()
    results[2] = result("ledger", "t3", status="failed", error="timeout")
    scripted_llm(RuntimeError("model unavailable"))
    final = await CEOAgent().synthesise(QUESTION, SUBTASKS, results)
    assert "delivery answer" in final.answer and "people answer" in final.answer
    assert {tuple(c.agents) for c in final.claims} == {("delivery",), ("people",)}
    assert final.claims[1].evidence_refs == ["allocations:id=7", "leave:id=2"]
    assert any("ledger" in u and "timeout" in u for u in final.unanswered)


async def test_fallback_with_no_results(scripted_llm):
    scripted_llm(RuntimeError("down"))
    final = await CEOAgent().synthesise(QUESTION, SUBTASKS, [])
    assert final.claims == []
    assert len(final.unanswered) == 3
