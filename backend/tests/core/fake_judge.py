"""A fake judge chat model for unit tests (never calls Groq).

Each scripted output is a dict validated into the requested schema, an Exception to raise, or
a callable(messages) returning either. Install it with `llm.override_judge_llm(lambda: fake)`.
"""

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

ScriptItem = dict[str, Any] | Exception | Callable[[list[BaseMessage]], Any]


def dims(**verdicts: str | tuple[str, float]) -> list[dict[str, Any]]:
    """dims(groundedness="pass", scope=("fail", 0.0)) -> structured dimension outputs."""
    out = []
    for name, value in verdicts.items():
        verdict, score = (
            value if isinstance(value, tuple) else (value, 1.0 if value == "pass" else 0.0)
        )
        out.append(
            {
                "dimension": name,
                "verdict": verdict,
                "score": score,
                "reasoning": f"{name} {verdict}",
            }
        )
    return out


def verdict(feedback: str = "", **verdicts: str | tuple[str, float]) -> dict[str, Any]:
    return {"dimensions": dims(**verdicts), "feedback": feedback}


ALL_PASS = verdict(groundedness="pass", completeness="pass", scope="pass")
GROUNDEDNESS_FAIL = verdict(
    "Remove the unsupported figure.", groundedness="fail", completeness="pass", scope="pass"
)


class FakeJudgeModel:
    def __init__(self, outputs: list[ScriptItem], usage: tuple[int, int] = (900, 150)) -> None:
        self.outputs = list(outputs)
        self.usage = usage
        self.calls: list[list[BaseMessage]] = []
        self.structured_kwargs: list[dict[str, Any]] = []

    def with_structured_output(self, schema: type[BaseModel], **kwargs: Any) -> "_Runnable":
        self.structured_kwargs.append(kwargs)
        return _Runnable(self, schema)


class _Runnable:
    def __init__(self, model: FakeJudgeModel, schema: type[BaseModel]) -> None:
        self.model = model
        self.schema = schema

    async def ainvoke(self, messages: list[BaseMessage]) -> dict[str, Any]:
        self.model.calls.append(list(messages))
        if not self.model.outputs:
            raise AssertionError("fake judge ran out of scripted outputs")
        item = self.model.outputs.pop(0)
        if callable(item) and not isinstance(item, Exception):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        input_tokens, output_tokens = self.model.usage
        raw = AIMessage(
            content="{}",
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )
        return {"raw": raw, "parsed": self.schema.model_validate(item), "parsing_error": None}
