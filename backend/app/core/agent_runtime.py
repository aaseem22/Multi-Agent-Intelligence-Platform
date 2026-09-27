"""The department agent runtime behind `DepartmentAgent.run`.

Each run builds a small subgraph, compiled without a checkpointer:

    react (create_agent: domain tools + ask_agent, structured AgentAnswer)
      -> finalize (AgentAnswer -> AgentResult, attaching only evidence tools/peers produced)
      -> self_check (eval_hooks.self_check, recorded as event + Langfuse score)

Any failure becomes AgentResult(status="failed"); nothing raises out of `run_department_agent`.
"""

import json
import logging
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core import eval_hooks, observability, prompts
from app.core.a2a import build_ask_agent_tool, describe_peers
from app.core.base_agent import CORE_AGENT_RULES, DepartmentAgent, tool_error
from app.core.config import get_settings
from app.core.context import AgentInvocation, emit, invocation_scope
from app.core.contracts import AgentAnswer, AgentResult, Evidence, Subtask
from app.core.events import AgentMode, AgentResultEvent, AgentStartedEvent, ToolCallEvent
from app.core.llm import get_llm, with_llm_retries
from app.core.registry import registry
from app.core.state import AgentRunState

logger = logging.getLogger(__name__)

MAX_FALLBACK_EVIDENCE = 20


# --- middleware ---


class LLMRetryMiddleware(AgentMiddleware):
    """Retry model calls with exponential backoff on 429 / 5xx only."""

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await with_llm_retries(lambda: handler(request))


class ToolEventMiddleware(AgentMiddleware):
    """Emit a tool_call event per tool call and turn tool exceptions into readable errors."""

    def __init__(self, agent: str, subtask_id: str) -> None:
        super().__init__()
        self.agent = agent
        self.subtask_id = subtask_id

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = request.tool_call
        args = json.loads(json.dumps(call.get("args") or {}, default=str))
        emit(
            ToolCallEvent,
            agent=self.agent,
            subtask_id=self.subtask_id,
            tool=call["name"],
            args=args,
        )
        try:
            return await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            logger.warning("Tool %s failed for %s: %s", call["name"], self.agent, exc)
            return ToolMessage(
                content=tool_error(f"tool {call['name']} failed: {exc}"),
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )


# --- prompt and tools ---


def _tools_for(agent: DepartmentAgent, mode: AgentMode, hop_count: int) -> list[BaseTool]:
    tools = list(agent.get_tools())
    may_delegate = mode == "task" or hop_count < get_settings().max_peer_hops
    ask_tool = build_ask_agent_tool(agent.name) if may_delegate else None
    if ask_tool is not None:
        tools.append(ask_tool)
    return tools


def _system_prompt(agent: DepartmentAgent, invocation: AgentInvocation, can_ask: bool) -> str:
    peers = registry.peer_cards(exclude=agent.name)
    peer_section = (
        f"{prompts.PEER_LIST_HEADER.format(max_calls=get_settings().max_peer_calls_per_agent)}"
        f"\n{describe_peers(peers)}"
        if peers and can_ask
        else prompts.NO_PEERS
    )
    if invocation.mode == "peer":
        mode_section = prompts.PEER_MODE_INSTRUCTIONS.format(
            requester=invocation.chain[-1] if invocation.chain else "a peer",
            hop_count=invocation.hop_count,
            chain=" -> ".join(invocation.chain) or "-",
            peer_rule=prompts.PEER_RULE_ALLOWED if can_ask else prompts.PEER_RULE_BLOCKED,
        )
    else:
        mode_section = prompts.TASK_MODE_INSTRUCTIONS
    return "\n\n".join(
        [agent.system_prompt().strip(), CORE_AGENT_RULES, peer_section, mode_section]
    )


def _instruction_with_context(
    instruction: str, context: list[AgentResult], invocation: AgentInvocation
) -> str:
    """Pre-register dependency evidence so it may be cited, and show it to the LLM."""
    if not context:
        return instruction
    lines = [instruction, "", prompts.CONTEXT_HEADER]
    for result in context:
        invocation.record_evidence(*result.evidence)
        lines.append(f"- {result.agent} ({result.status}): {result.answer or result.error or ''}")
        lines.extend(f"    - {e.source_ref}: {e.summary}" for e in result.evidence)
    return "\n".join(lines)


# --- subgraph ---


def _last_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.text.strip():
            return message.text.strip()
    return ""


def _resolve_evidence(answer: AgentAnswer, invocation: AgentInvocation) -> list[Evidence]:
    known = invocation.evidence
    cited: list[Evidence] = []
    for ref in dict.fromkeys(answer.evidence_refs):
        if ref in known:
            cited.append(known[ref])
        else:
            logger.warning("%s cited unknown evidence ref %r; dropped", invocation.agent, ref)
    return cited or list(known.values())[:MAX_FALLBACK_EVIDENCE]


def _finalize(state: AgentRunState, invocation: AgentInvocation) -> AgentResult:
    common = {
        "agent": invocation.agent,
        "subtask_id": invocation.subtask_id,
        "peer_messages": list(invocation.peer_messages),
    }
    raw = state.get("answer")
    if raw is None:
        return AgentResult(
            **common,
            status="partial",
            answer=state.get("last_text") or prompts.NO_STRUCTURED_ANSWER,
            evidence=list(invocation.evidence.values())[:MAX_FALLBACK_EVIDENCE],
            error=prompts.NO_STRUCTURED_ANSWER,
        )
    answer = AgentAnswer.model_validate(raw)
    return AgentResult(
        **common,
        status=answer.status,
        answer=answer.answer,
        evidence=_resolve_evidence(answer, invocation),
    )


def build_agent_graph(
    agent: DepartmentAgent, invocation: AgentInvocation, subtask: Subtask
) -> CompiledStateGraph:
    tools = _tools_for(agent, invocation.mode, invocation.hop_count)
    can_ask = any(t.name == "ask_agent" for t in tools)
    react_agent = create_agent(
        model=get_llm("agent"),
        tools=tools,
        system_prompt=_system_prompt(agent, invocation, can_ask),
        response_format=ToolStrategy(AgentAnswer),
        middleware=[LLMRetryMiddleware(), ToolEventMiddleware(agent.name, invocation.subtask_id)],
        checkpointer=False,
        name=f"{agent.name}_react",
    )
    recursion_limit = get_settings().graph_recursion_limit

    async def react(state: AgentRunState) -> dict[str, Any]:
        out = await react_agent.ainvoke(
            {"messages": [HumanMessage(state["instruction"])]},
            config={"recursion_limit": recursion_limit},
        )
        structured = out.get("structured_response")
        return {
            "answer": structured.model_dump() if isinstance(structured, AgentAnswer) else None,
            "last_text": _last_text(out.get("messages", [])),
        }

    async def finalize(state: AgentRunState) -> dict[str, Any]:
        return {"result": _finalize(state, invocation).model_dump(mode="json")}

    async def self_check(state: AgentRunState) -> dict[str, Any]:
        result = AgentResult.model_validate(state["result"])
        evaluation = await eval_hooks.self_check(result, subtask)
        observability.record_eval(evaluation, invocation.agent, invocation.subtask_id)
        return {}

    return (
        StateGraph(AgentRunState)
        .add_node("react", react)
        .add_node("finalize", finalize)
        .add_node("self_check", self_check)
        .add_edge(START, "react")
        .add_edge("react", "finalize")
        .add_edge("finalize", "self_check")
        .add_edge("self_check", END)
        .compile(checkpointer=False, name=f"agent:{agent.name}")
    )


def _failed(invocation: AgentInvocation, error: str) -> AgentResult:
    return AgentResult(
        agent=invocation.agent,
        subtask_id=invocation.subtask_id,
        status="failed",
        answer="",
        evidence=[],
        peer_messages=list(invocation.peer_messages),
        error=error,
    )


async def run_department_agent(
    agent: DepartmentAgent,
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
    invocation = AgentInvocation(
        agent=agent.name,
        subtask_id=subtask_id,
        mode=mode,
        hop_count=hop_count,
        chain=list(chain or []),
    )
    subtask = Subtask(id=subtask_id, assigned_to=agent.name, instruction=instruction)
    with invocation_scope(invocation):
        emit(
            AgentStartedEvent,
            agent=agent.name,
            subtask_id=subtask_id,
            mode=mode,
            instruction=instruction,
        )
        try:
            prompt = _instruction_with_context(instruction, context or [], invocation)
            graph = build_agent_graph(agent, invocation, subtask)
            config = {
                "recursion_limit": get_settings().graph_recursion_limit,
                "run_name": run_name or f"agent:{agent.name}",
                "metadata": {
                    "agent": agent.name,
                    "subtask_id": subtask_id,
                    "mode": mode,
                    "hop_count": hop_count,
                    "chain": invocation.chain,
                    **(metadata or {}),
                },
                "tags": [f"agent:{agent.name}"],
            }
            with observability.agent_tags(agent.name):
                state = await graph.ainvoke({"instruction": prompt}, config=config)
            result = AgentResult.model_validate(state["result"])
        except Exception as exc:
            logger.exception("Agent %s failed on subtask %s", agent.name, subtask_id)
            result = _failed(invocation, f"{type(exc).__name__}: {exc}")
        emit(AgentResultEvent, mode=mode, result=result)
        return result
