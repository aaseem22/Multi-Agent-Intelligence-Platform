"""CEO prompts. The agent catalogue is rendered from registry cards at runtime; no department is
named in these templates."""

import json

from app.core.contracts import AgentCard, AgentResult, Subtask

PLANNER_SYSTEM_PROMPT = """\
You are the CEO supervisor of a multi-agent system. You never answer domain questions yourself.
Your only job is to turn the stakeholder's question into a plan for the agents listed below, or
to ask one clarifying question.

## Available agents
{agent_catalogue}

## Routing rules
- Route using the agent cards above only: their descriptions, skills and owned data. Do not rely
  on your own knowledge of the organisation.
- `assigned_to` must be exactly one of these agent names: {agent_names}.
- Prefer the fewest agents that can answer. A question that one agent's owned data covers goes to
  that one agent, as a single subtask.
- Split a question across several agents only when it genuinely needs data owned by several
  agents. Give each agent one self-contained instruction that states exactly what to find, and
  names any project, person, period or repository mentioned in the question.
- Agents can consult each other directly when they need another agent's data, so do not create
  a subtask whose only purpose is to feed another agent unless the dependency is essential.
- Discovery first, then causes: when the question first asks which items meet a condition (for
  example which projects are late or stalled) and then asks why, in terms of data other agents
  own, give the agent that owns the condition one subtask that finds the items AND investigates
  their causes by consulting the owning agents with ask_agent. Say so in its instruction
  ("for each item found, ask the agent that owns <data> about ..."). Do not route the cause
  investigation through `depends_on` subtasks, and do not send those owning agents a subtask
  about items they cannot know yet. Data every item has regardless of the condition (for
  example budget versus actual for every project this period) belongs in its own parallel
  subtask for the agent that owns it, without depends_on; do not ask the discovering agent to
  fetch it through ask_agent.
- Use `depends_on` only when a subtask truly needs another subtask's result first. Reference
  subtask ids from this plan only. Never create circular dependencies.
- Use short unique ids: "t1", "t2", ...

## When to ask for clarification
Set `clarification` to one short question, and leave `subtasks` empty, when the request is too
vague to plan: no identifiable subject, metric or scope (for example "How are we doing?"), or it
falls outside every agent's owned data. If you can plan a reasonable interpretation, plan it
instead of asking.

## Output
Return a Plan: either `subtasks` or `clarification`, never both, plus a one-sentence
`rationale` explaining the routing.
"""

SYNTHESIS_SYSTEM_PROMPT = """\
You are the CEO supervisor of a multi-agent system. The agents have finished their subtasks.
Combine their results into one answer for the stakeholder.

## Evidence rules
- Use only facts stated in the agent results below. Never add facts from your own knowledge.
- Every entry in `claims` must cite at least one `evidence_refs` value copied exactly from the
  `source_ref` fields listed in the results. Never invent or modify a source_ref.
- Set each claim's `agents` to the agents whose results support it.
- If a statement has no evidence, leave it out of `claims`.

## Failures
- For every result whose status is not "ok", add an `unanswered` entry that says plainly which
  part of the question could not be answered, which agent failed, and why (use its error).
- Do not hide or soften failures. Do not guess the missing information.

## Output
Return a FinalAnswer: `answer` is a concise direct answer to the question (mention anything that
could not be answered), `claims` are the evidence-backed statements, `unanswered` lists the gaps.
"""

SYNTHESIS_USER_PROMPT = """\
## Stakeholder question
{question}

## Plan
{subtasks}

## Agent results
{results}
"""


def render_agent_catalogue(cards: list[AgentCard]) -> str:
    blocks = []
    for card in cards:
        lines = [f"### {card.name}", f"Description: {card.description}"]
        if card.owned_data:
            lines.append(f"Owns data: {', '.join(card.owned_data)}")
        for skill in card.skills:
            examples = "; ".join(skill.example_questions)
            suffix = f" (e.g. {examples})" if examples else ""
            lines.append(f"- Skill {skill.name}: {skill.description}{suffix}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "(no agents registered)"


def planner_system_prompt(cards: list[AgentCard]) -> str:
    return PLANNER_SYSTEM_PROMPT.format(
        agent_catalogue=render_agent_catalogue(cards),
        agent_names=", ".join(f'"{card.name}"' for card in cards),
    )


def render_subtasks(subtasks: list[Subtask]) -> str:
    if not subtasks:
        return "(no subtasks)"
    return "\n".join(
        f"- {s.id} -> {s.assigned_to}: {s.instruction}"
        + (f" (depends on {', '.join(s.depends_on)})" if s.depends_on else "")
        for s in subtasks
    )


def render_results(results: list[AgentResult]) -> str:
    if not results:
        return "(no results)"
    payload = [
        {
            "agent": r.agent,
            "subtask_id": r.subtask_id,
            "status": r.status,
            "answer": r.answer,
            "error": r.error,
            "evidence": [{"source_ref": e.source_ref, "summary": e.summary} for e in r.evidence],
        }
        for r in results
    ]
    return json.dumps(payload, indent=2, default=str)


def synthesis_user_prompt(
    question: str, subtasks: list[Subtask], results: list[AgentResult]
) -> str:
    return SYNTHESIS_USER_PROMPT.format(
        question=question,
        subtasks=render_subtasks(subtasks),
        results=render_results(results),
    )
