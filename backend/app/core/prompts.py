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

PEER_LIST_HEADER = "## Peer agents you can ask with ask_agent"
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

Available agents:
{peers}"""

NO_STRUCTURED_ANSWER = "The agent did not return a structured answer."
