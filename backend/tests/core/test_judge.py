"""The independent judge (Groq by default) with a fake model: no network."""

import httpx
import pytest

from app.core import judge as judge_module
from app.core import llm
from app.core.config import get_settings
from app.core.contracts import Evidence
from app.core.judge import AGENT_ANSWER_RUBRIC, JudgeInput, judge, render_material
from app.core.llm import TokenBucketLimiter, groq_retry_delay, override_judge_llm, parse_duration
from tests.core.fake_judge import ALL_PASS, FakeJudgeModel, verdict


@pytest.fixture(autouse=True)
def judge_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "judge_provider", "groq")
    monkeypatch.setattr(settings, "groq_judge_model", "openai/gpt-oss-120b")
    llm.get_judge_limiter.cache_clear()
    judge_module.reset_judge_usage()


ITEM = JudgeInput(
    question="What is the spend versus budget on Customer Portal this quarter?",
    answer="Customer Portal spent INR 4,52,300 against a budget of INR 5,00,000.",
    evidence=[
        Evidence(
            source_type="db",
            source_ref="budgets:id=7",
            summary="Customer Portal 2026-Q4 budget",
            data={"amount": 500000},
        ),
        Evidence(
            source_type="db",
            source_ref="expenses:project_id=3",
            summary="Customer Portal spend 2026-Q4",
            data={"total": 452300},
        ),
    ],
)


async def test_judge_parses_structured_verdict_and_tracks_usage():
    fake = FakeJudgeModel([ALL_PASS])
    with override_judge_llm(lambda: fake):
        result = await judge(AGENT_ANSWER_RUBRIC, ITEM)
    assert result.error is None
    assert result.passed and result.score == 1.0
    assert [d.dimension for d in result.dimensions] == ["groundedness", "completeness", "scope"]
    assert result.model == "openai/gpt-oss-120b"
    assert result.feedback == ""
    assert fake.structured_kwargs == [
        {"method": "json_schema", "strict": True, "include_raw": True}
    ]
    usage = judge_module.judge_usage()
    assert usage.calls == 1 and usage.last == {"input_tokens": 900, "output_tokens": 150}


async def test_judge_prompt_carries_question_answer_evidence_only():
    fake = FakeJudgeModel([ALL_PASS])
    with override_judge_llm(lambda: fake):
        await judge(AGENT_ANSWER_RUBRIC, ITEM)
    system, human = fake.calls[0]
    assert "independent reviewer" in system.text
    assert "budgets:id=7: Customer Portal 2026-Q4 budget | data:" in human.text
    assert "groundedness" in human.text and ITEM.question in human.text


def test_material_is_truncated_to_budget():
    many = [
        Evidence(source_type="db", source_ref=f"expenses:id={i}", summary="x" * 150, data={"v": i})
        for i in range(200)
    ]
    material = render_material(JudgeInput(question="q" * 5000, answer="a" * 20000, evidence=many))
    assert len(material) < 13_000  # ~3.3K tokens, inside Groq's 8K tokens/min
    assert "more evidence items omitted" in material
    assert "[truncated]" in material


async def test_unknown_dimensions_are_excluded_from_score():
    fake = FakeJudgeModel(
        [
            verdict(
                "Support the cost figure.",
                groundedness="pass",
                completeness="unknown",
                scope="fail",
            )
        ]
    )
    with override_judge_llm(lambda: fake):
        result = await judge(AGENT_ANSWER_RUBRIC, ITEM)
    # groundedness 1.0 (w=1) and scope 0.0 (w=0.5); completeness excluded
    assert result.score == pytest.approx(1 / 1.5, abs=1e-3)
    assert not result.passed
    assert result.feedback == "Support the cost figure."
    unknown = next(d for d in result.dimensions if d.dimension == "completeness")
    assert unknown.verdict == "unknown" and unknown.score == 0.0


async def test_all_unknown_passes_with_no_score():
    fake = FakeJudgeModel(
        [verdict(groundedness="unknown", completeness="unknown", scope="unknown")]
    )
    with override_judge_llm(lambda: fake):
        result = await judge(AGENT_ANSWER_RUBRIC, ITEM)
    assert result.passed and result.score is None


async def test_missing_dimension_becomes_unknown_and_failure_has_feedback():
    fake = FakeJudgeModel([verdict(groundedness=("fail", 0.0))])
    with override_judge_llm(lambda: fake):
        result = await judge(AGENT_ANSWER_RUBRIC, ITEM)
    assert [d.verdict for d in result.dimensions] == ["fail", "unknown", "unknown"]
    assert result.score == 0.0 and not result.passed
    assert "groundedness" in result.feedback  # built from failing reasoning


async def test_judge_failure_never_raises():
    fake = FakeJudgeModel([ValueError("schema mismatch")])
    with override_judge_llm(lambda: fake):
        result = await judge(AGENT_ANSWER_RUBRIC, ITEM)
    assert result.passed and result.score is None
    assert result.error and "schema mismatch" in result.error


async def test_missing_groq_key_is_a_judge_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "groq_api_key", "")
    result = await judge(AGENT_ANSWER_RUBRIC, ITEM)
    assert result.passed and result.error and "GROQ_API_KEY" in result.error


def _rate_limited(headers: dict[str, str]) -> Exception:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, headers=headers, request=request)
    exc = RuntimeError("Error code: 429 - rate_limit_exceeded")
    exc.status_code = 429  # type: ignore[attr-defined]
    exc.response = response  # type: ignore[attr-defined]
    return exc


async def test_judge_retries_429_then_succeeds():
    fake = FakeJudgeModel([_rate_limited({"retry-after": "3"}), ALL_PASS])
    with override_judge_llm(lambda: fake):
        result = await judge(AGENT_ANSWER_RUBRIC, ITEM)
    assert result.error is None and result.passed
    assert len(fake.calls) == 2


async def test_judge_gives_up_when_server_wait_is_too_long():
    fake = FakeJudgeModel([_rate_limited({"retry-after": "3600"}), ALL_PASS])
    with override_judge_llm(lambda: fake):
        result = await judge(AGENT_ANSWER_RUBRIC, ITEM)
    assert result.error and result.passed and result.score is None
    assert len(fake.calls) == 1  # a daily quota is not waited out


async def test_isolated_mode_makes_one_call_per_dimension():
    outputs = [
        {"dimension": "x", "verdict": "pass", "score": 1.0, "reasoning": "ok"},
        {"dimension": "x", "verdict": "fail", "score": 0.0, "reasoning": "misses part 2"},
        {"dimension": "x", "verdict": "pass", "score": 1.0, "reasoning": "ok"},
    ]
    fake = FakeJudgeModel(outputs)
    with override_judge_llm(lambda: fake):
        result = await judge(AGENT_ANSWER_RUBRIC, ITEM, isolated=True)
    assert len(fake.calls) == 3
    assert [d.dimension for d in result.dimensions] == ["groundedness", "completeness", "scope"]
    assert result.score == pytest.approx(1.5 / 2.5)
    assert not result.passed and "completeness: misses part 2" in result.feedback


# --- token limiter and retry headers ---


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_token_bucket_waits_for_refill():
    clock = FakeClock()
    limiter = TokenBucketLimiter(600, clock=clock, sleep=clock.sleep)  # 10 tokens / second
    assert await limiter.acquire(600) == 0.0
    waited = await limiter.acquire(300)
    assert waited == pytest.approx(30.0)
    assert clock.now == pytest.approx(30.0)


async def test_token_bucket_clamps_oversized_requests_and_settles():
    clock = FakeClock()
    limiter = TokenBucketLimiter(600, clock=clock, sleep=clock.sleep)
    assert await limiter.acquire(5000) == 0.0  # clamped to capacity, still runs
    limiter.settle(estimated=600, actual=300)  # 300 refunded
    assert limiter.wait_time(300) == 0.0
    limiter.settle(estimated=0, actual=600)  # real usage exceeded the estimate
    assert limiter.wait_time(300) == pytest.approx(60.0)


def test_groq_retry_delay_reads_headers():
    assert groq_retry_delay(_rate_limited({"retry-after": "7"})) == 7.0
    assert groq_retry_delay(_rate_limited({"x-ratelimit-reset-tokens": "2m59.56s"})) == (
        pytest.approx(179.56)
    )
    assert groq_retry_delay(_rate_limited({})) is None
    assert parse_duration("120ms") == pytest.approx(0.12)


def test_peer_evidence_shows_the_peer_answer_and_its_sources():
    peer = Evidence(
        source_type="peer",
        source_ref="peer:hr:msg_1",
        summary="hr answered (ok): ...",
        data={
            "answer": "Ml Forecasting is 47 days late; lead allocated 180%.",
            "peer_evidence": [{"source_ref": "allocations:id=16", "summary": "Lead at 180%"}],
        },
    )
    material = render_material(JudgeInput(question="q", answer="a", evidence=[peer]))
    assert "47 days late" in material and "allocations:id=16: Lead at 180%" in material
