"""Prompt fragments core appends to every department agent. Department-agnostic: peer names
and descriptions are generated from the registry at runtime."""

TASK_MODE_INSTRUCTIONS = """
## Mode: task
You are handling a subtask assigned by the supervisor. Use your tools, ask a peer only when you
need data another department owns, then give your final answer as the structured response.
""".strip()

PEER_MODE_INSTRUCTIONS = """
## Mode: peer request
Another department agent ({requester}) is asking you a question (hop {hop_count}, chain:
{chain}). Answer only from your own domain and tools, briefly and with figures. {peer_rule}
Give your final answer as the structured response.
""".strip()

PEER_RULE_ALLOWED = "You may ask another peer only if you truly need data you do not own."
PEER_RULE_BLOCKED = "You cannot ask other agents; the delegation hop limit has been reached."

PEER_LIST_HEADER = """## Peer agents you can ask with ask_agent
You may make at most {max_calls} ask_agent calls for this request. Ask each agent at most once:
put every item you need (all projects, people or periods) into that one question."""
NO_PEERS = "## Peer agents\nNo peer agents are available. Work only with your own tools."

CONTEXT_HEADER = """
## Results from earlier subtasks
You may use these results and cite their source_ref values exactly as listed.
""".strip()

ASK_AGENT_DESCRIPTION = """Ask another department agent a question about data it owns. Use this
only when you need information outside your own domain. Pass the agent's name as `target` and a
specific, self-contained question. The reply is JSON with `answer`, `status` and a `source_ref`
(starting with "peer:") that you must cite in evidence_refs. A reply starting with "REFUSED"
means the request was blocked (hop limit, cycle or call limit): continue with what you have.
You have at most {max_calls} calls per request, so ask each agent once and include every item
you need in that single question instead of one call per item.

Available agents:
{peers}"""

NO_STRUCTURED_ANSWER = "The agent did not return a structured answer."

# --- independent judge (app/core/judge.py). The judge never sees the agent's system prompt. ---

JUDGE_SYSTEM = """You are an independent reviewer grading an answer produced by an enterprise
department agent. Judge each rubric dimension separately, using only the question, the answer and
the evidence shown. Do not use outside knowledge and do not reward fluent wording.
For each dimension give:
- verdict: "pass", "fail", or "unknown" when the material shown is not enough to decide (for
  example the evidence was truncated). Prefer "unknown" over guessing.
- score: 1 for pass, 0 for fail, a value in between for partial credit, 0 for unknown.
- reasoning: one or two sentences citing the evidence refs you relied on.
Simple arithmetic on evidence figures (sums, differences, percentages) counts as supported.
An answer that plainly states what it could not find is not a completeness failure."""

JUDGE_FEEDBACK_RULE = """feedback: if any dimension fails, write 1-3 short, concrete instructions
the agent can follow to fix its answer (which claim to remove or support, which part to add).
Leave it empty when everything passes."""

JUDGE_DIMENSION_LINE = "- {name}: {question} PASS: {passing} FAIL: {failing}"

RETRY_FEEDBACK_HEADER = """## Reviewer feedback from a previous attempt
A reviewer checked your previous answer to this instruction and found problems. Answer the
instruction again from your tools, fixing these points, and cite evidence for every figure:"""
