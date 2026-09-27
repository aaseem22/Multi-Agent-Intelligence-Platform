// One ink per agent, used wherever an agent is named. Departments registered later
// fall back to a stable ink from the overflow set.

const KNOWN_INK: Record<string, string> = {
  ceo: "text-agent-ceo",
  finance: "text-agent-finance",
  hr: "text-agent-hr",
  tech: "text-agent-tech",
};

const KNOWN_STROKE: Record<string, string> = {
  ceo: "bg-agent-ceo",
  finance: "bg-agent-finance",
  hr: "bg-agent-hr",
  tech: "bg-agent-tech",
};

const OVERFLOW_INK = ["text-agent-other-1", "text-agent-other-2", "text-agent-other-3"];
const OVERFLOW_STROKE = ["bg-agent-other-1", "bg-agent-other-2", "bg-agent-other-3"];

function overflowIndex(name: string): number {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash % OVERFLOW_INK.length;
}

/** Text colour class for an agent's name. */
export function agentInk(name: string): string {
  return KNOWN_INK[name] ?? OVERFLOW_INK[overflowIndex(name)];
}

/** Background colour class for an agent's timeline node or margin rule. */
export function agentStroke(name: string): string {
  return KNOWN_STROKE[name] ?? OVERFLOW_STROKE[overflowIndex(name)];
}

const LABELS: Record<string, string> = { ceo: "CEO", hr: "HR" };

export function agentLabel(name: string): string {
  return LABELS[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
}
