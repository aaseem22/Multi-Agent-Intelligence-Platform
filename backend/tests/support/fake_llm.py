"""Scripted chat model for unit tests. Never call Gemini in unit tests.

Usage:
    llm = ScriptedChatModel(responses=[
        tool_call("budget_vs_actual", {"period": "2026-Q3"}),
        tool_call("AgentAnswer", {"status": "ok", "answer": "...", "evidence_refs": ["budgets:id=1"]}),
    ])
    with override_llm(lambda role: llm):
        result = await FinanceAgent().run("...", subtask_id="t1")

Structured output via create_agent(response_format=ToolStrategy(Schema)) is itself a tool call
named after the schema class, so scripting it is just another `tool_call(...)`.
For `llm.with_structured_output(Schema)` callers, pass `structured=[Schema(...), ...]`.
"""

import itertools
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, PrivateAttr

_ids = itertools.count(1)


def tool_call(name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}"}]
    )


def text(content: str) -> AIMessage:
    return AIMessage(content=content)


class ScriptedChatModel(BaseChatModel):
    responses: list[AIMessage] = []
    structured: list[Any] = []
    _cursor: int = PrivateAttr(default=0)
    _structured_cursor: int = PrivateAttr(default=0)
    calls: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        if self._cursor >= len(self.responses):
            raise AssertionError(f"ScriptedChatModel ran out of responses after {self._cursor}")
        message = self.responses[self._cursor]
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable:
        def respond(_: Any) -> Any:
            if self._structured_cursor >= len(self.structured):
                raise AssertionError("ScriptedChatModel ran out of structured responses")
            value = self.structured[self._structured_cursor]
            self._structured_cursor += 1
            if isinstance(value, Exception):
                raise value
            if (
                isinstance(schema, type)
                and issubclass(schema, BaseModel)
                and isinstance(value, dict)
            ):
                return schema.model_validate(value)
            return value

        return RunnableLambda(respond)
