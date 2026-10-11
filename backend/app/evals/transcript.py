"""Read-only view over a trial transcript: the serialized stream events of one request."""

from dataclasses import dataclass
from typing import Any


@dataclass
class TrialView:
    events: list[dict[str, Any]]
    duration_ms: int = 0
    llm_calls: int = 0

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("type") == type_]

    # --- plan and routing ---

    @property
    def planned_agents(self) -> list[str]:
        seen: list[str] = []
        for plan in self.of("plan"):
            for subtask in plan.get("subtasks", []):
                agent = subtask.get("assigned_to")
                if agent and agent not in seen:
                    seen.append(agent)
        return seen

    @property
    def subtask_count(self) -> int:
        return sum(len(p.get("subtasks", [])) for p in self.of("plan"))

    @property
    def peer_requests(self) -> list[dict[str, Any]]:
        """Peer requests that were delivered (not refused by a guard)."""
        return [
            e
            for e in self.of("peer_message")
            if e["message"]["type"] == "peer_request" and not e.get("refused")
        ]

    @property
    def attempted_peer_requests(self) -> list[dict[str, Any]]:
        return [e for e in self.of("peer_message") if e["message"]["type"] == "peer_request"]

    @property
    def refusals(self) -> list[dict[str, Any]]:
        return [e for e in self.of("peer_message") if e.get("refused")]

    @property
    def peer_recipients(self) -> list[str]:
        return sorted({e["message"]["recipient"] for e in self.peer_requests})

    @property
    def involved_agents(self) -> list[str]:
        return sorted(set(self.planned_agents) | set(self.peer_recipients))

    @property
    def agents_started(self) -> list[dict[str, Any]]:
        return self.of("agent_started")

    # --- outcome ---

    @property
    def final(self) -> dict[str, Any] | None:
        finals = self.of("final")
        return finals[-1] if finals else None

    @property
    def clarification(self) -> str | None:
        items = self.of("clarification")
        return items[-1]["question"] if items else None

    @property
    def final_answer(self) -> str | None:
        final = self.final
        return final["answer"]["answer"] if final else None

    @property
    def unanswered(self) -> list[str]:
        final = self.final
        return list(final["answer"].get("unanswered", [])) if final else []

    @property
    def claims(self) -> list[dict[str, Any]]:
        final = self.final
        return list(final["answer"].get("claims", [])) if final else []

    @property
    def answer_text(self) -> str:
        """Everything the stakeholder reads: answer, claims and unanswered notes (or the
        clarification question when the CEO asked back)."""
        final = self.final
        if final is None:
            return self.clarification or ""
        parts = [final["answer"].get("answer", "")]
        parts += [c.get("text", "") for c in self.claims]
        parts += self.unanswered
        return "\n".join(p for p in parts if p)

    @property
    def agent_results(self) -> list[dict[str, Any]]:
        """Every AgentResult seen in the trial: task and peer mode, plus the final's results."""
        results = [e["result"] for e in self.of("agent_result")]
        final = self.final
        if final:
            results += final.get("results", [])
        return results

    @property
    def evidence(self) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for result in self.agent_results:
            for item in result.get("evidence", []):
                seen.setdefault(item["source_ref"], item)
        return list(seen.values())

    @property
    def evidence_refs(self) -> set[str]:
        return {e["source_ref"] for e in self.evidence}

    @property
    def errors(self) -> list[dict[str, Any]]:
        return self.of("error")

    @property
    def failed_results(self) -> list[dict[str, Any]]:
        unique = {
            (r.get("agent"), r.get("subtask_id")): r
            for r in self.agent_results
            if r.get("status") == "failed"
        }
        return list(unique.values())

    @property
    def recoveries(self) -> list[dict[str, Any]]:
        return self.of("recovery")

    @property
    def trace_url(self) -> str | None:
        final = self.final
        return final.get("trace_url") if final else None
