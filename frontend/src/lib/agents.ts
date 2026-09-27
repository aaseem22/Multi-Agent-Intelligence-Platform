// One colour per agent, used everywhere an agent name appears. New departments added
// later fall back to a stable colour from the overflow palette.

interface AgentTone {
  text: string;
  bg: string;
  border: string;
  dot: string;
}

const KNOWN: Record<string, AgentTone> = {
  ceo: {
    text: "text-agent-ceo",
    bg: "bg-agent-ceo/10",
    border: "border-agent-ceo/40",
    dot: "bg-agent-ceo",
  },
  finance: {
    text: "text-agent-finance",
    bg: "bg-agent-finance/10",
    border: "border-agent-finance/40",
    dot: "bg-agent-finance",
  },
  hr: {
    text: "text-agent-hr",
    bg: "bg-agent-hr/10",
    border: "border-agent-hr/40",
    dot: "bg-agent-hr",
  },
  tech: {
    text: "text-agent-tech",
    bg: "bg-agent-tech/10",
    border: "border-agent-tech/40",
    dot: "bg-agent-tech",
  },
};

const OVERFLOW: AgentTone[] = [
  { text: "text-agent-other", bg: "bg-agent-other/10", border: "border-agent-other/40", dot: "bg-agent-other" },
  { text: "text-teal-700", bg: "bg-teal-700/10", border: "border-teal-700/40", dot: "bg-teal-700" },
  { text: "text-rose-700", bg: "bg-rose-700/10", border: "border-rose-700/40", dot: "bg-rose-700" },
  { text: "text-lime-700", bg: "bg-lime-700/10", border: "border-lime-700/40", dot: "bg-lime-700" },
];

export function agentTone(name: string): AgentTone {
  const known = KNOWN[name];
  if (known) return known;
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return OVERFLOW[hash % OVERFLOW.length];
}

const LABELS: Record<string, string> = { ceo: "CEO", hr: "HR" };

export function agentLabel(name: string): string {
  return LABELS[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
}
