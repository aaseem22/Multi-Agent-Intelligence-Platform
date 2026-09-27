"""DepartmentAgent base class and the helpers department tools use to return evidence.

Public API (frozen; department agents code against it):

    class FinanceAgent(DepartmentAgent):
        card = FINANCE_CARD
        def get_tools(self) -> list[BaseTool]: ...
        def system_prompt(self) -> str: ...

    registry.register(FinanceAgent())

Inside a tool:

    rows = await finance_repo.budget_vs_actual(period)
    return evidence_result(
        [r.model_dump(mode="json") for r in rows],
        [db_evidence(ref, f"Budget vs actual for {r.project_name}") for r in rows for ref in r.refs],
    )

`evidence_result` records the Evidence on the running invocation and returns a JSON string that
lists each `source_ref`. The LLM cites those refs in `AgentAnswer.evidence_refs`; `run` attaches
only evidence that tools or peers actually produced, so evidence cannot be invented.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from langchain_core.tools import BaseTool

from app.core.context import current_invocation
from app.core.contracts import AgentCard, AgentResult, Evidence
from app.core.events import AgentMode

MAX_EVIDENCE_DATA_CHARS = 1500

CORE_AGENT_RULES = """
## Rules that apply to every department agent
- Answer only from your own tools' outputs and from answers returned by ask_agent.
- Never guess figures, names or dates. If your tools return nothing, say so.
- Every tool output lists `evidence` entries with a `source_ref`. In your final answer, put the
  exact `source_ref` values that support it in `evidence_refs`. Never make up a source_ref.
- When you need data another department owns, call ask_agent with that department's agent name.
  Its reply includes a `source_ref` beginning with `peer:`; cite it like any other evidence.
- If ask_agent returns a refusal, carry on with what you have and report status "partial".
- If the instruction is outside your domain and no peer can help, report "needs_clarification".
""".strip()


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _small(data: Any) -> dict | None:
    if data is None:
        return None
    data = _jsonable(data)
    if not isinstance(data, dict):
        data = {"value": data}
    return data if len(json.dumps(data)) <= MAX_EVIDENCE_DATA_CHARS else None


def db_evidence(source_ref: str, summary: str, data: Any = None) -> Evidence:
    """Evidence for database records, e.g. source_ref="budgets:id=42"."""
    return Evidence(source_type="db", source_ref=source_ref, summary=summary, data=_small(data))


def github_evidence(source_ref: str, summary: str, data: Any = None) -> Evidence:
    """Evidence for a GitHub API response; use GitHubResult.source_ref, e.g. "github:repos/o/r/pulls?state=open"."""
    return Evidence(source_type="github", source_ref=source_ref, summary=summary, data=_small(data))


def record_evidence(*items: Evidence) -> None:
    """Attach evidence to the running agent invocation. A no-op outside a run (unit tests)."""
    invocation = current_invocation()
    if invocation is not None:
        invocation.record_evidence(*items)


def evidence_result(data: Any, evidence: list[Evidence]) -> str:
    """What every department tool returns: data plus the evidence refs the LLM may cite."""
    record_evidence(*evidence)
    return json.dumps(
        {
            "data": _jsonable(data),
            "evidence": [{"source_ref": e.source_ref, "summary": e.summary} for e in evidence],
        },
        default=str,
    )


def tool_error(message: str, **details: Any) -> str:
    """Tool failure the LLM can read and recover from. Never raise out of a tool."""
    return json.dumps({"error": message, **_jsonable(details)}, default=str)


class DepartmentAgent(ABC):
    """A department agent: a tool-calling LangGraph subgraph plus the core `ask_agent` tool.

    Subclasses set `card` and implement `get_tools` and `system_prompt`. They never override
    `run`; core owns the loop, structured output, evidence, A2A, eval hooks and events.
    """

    card: ClassVar[AgentCard]

    @property
    def name(self) -> str:
        return self.card.name

    @abstractmethod
    def get_tools(self) -> list[BaseTool]:
        """The agent's own read-only domain tools (ask_agent is added by core)."""

    @abstractmethod
    def system_prompt(self) -> str:
        """Department prompt: scope, tools, when to ask peers, refusals. Core appends
        CORE_AGENT_RULES, the peer list and the task/peer mode instructions."""

    async def run(
        self,
        instruction: str,
        *,
        subtask_id: str,
        mode: AgentMode = "task",
        hop_count: int = 0,
        chain: list[str] | None = None,
        context: list[AgentResult] | None = None,
        run_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Run the agent and always return an AgentResult (status="failed" on any error).

        Builds the subgraph (create_agent with get_tools() + ask_agent, structured output
        AgentAnswer -> AgentResult, then eval_hooks.self_check), sets the AgentInvocation
        context, emits agent_started / tool_call / agent_result / eval_result events, and applies
        LLM retries and the recursion limit. `context` holds results of dependency subtasks whose
        evidence this run may cite. Implemented in app/core/agent_runtime.py.
        """
        from app.core.agent_runtime import run_department_agent

        return await run_department_agent(
            self,
            instruction,
            subtask_id=subtask_id,
            mode=mode,
            hop_count=hop_count,
            chain=chain,
            context=context,
            run_name=run_name,
            metadata=metadata,
        )
