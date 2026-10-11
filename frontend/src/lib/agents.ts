// One hue per agent, used wherever an agent is named, drawn or charted. Departments registered
// later fall back to a stable hue from the overflow set. `color` and `softColor` are CSS variable
// references to the --color-agent-* tokens, so SVG charts follow the light and dark themes.

interface AgentStyle {
  color: string;
  softColor: string;
  text: string;
  bg: string;
  soft: string;
}

// Class names are spelled out in full so Tailwind can find them.
const KNOWN: Record<string, AgentStyle> = {
  ceo: { color: "var(--color-agent-ceo)", softColor: "var(--color-agent-ceo-soft)", text: "text-agent-ceo", bg: "bg-agent-ceo", soft: "bg-agent-ceo-soft" },
  finance: {
    color: "var(--color-agent-finance)",
    softColor: "var(--color-agent-finance-soft)",
    text: "text-agent-finance",
    bg: "bg-agent-finance",
    soft: "bg-agent-finance-soft",
  },
  hr: { color: "var(--color-agent-hr)", softColor: "var(--color-agent-hr-soft)", text: "text-agent-hr", bg: "bg-agent-hr", soft: "bg-agent-hr-soft" },
  tech: { color: "var(--color-agent-tech)", softColor: "var(--color-agent-tech-soft)", text: "text-agent-tech", bg: "bg-agent-tech", soft: "bg-agent-tech-soft" },
};

const OVERFLOW: AgentStyle[] = [
  { color: "var(--color-agent-other-1)", softColor: "var(--color-agent-other-1-soft)", text: "text-agent-other-1", bg: "bg-agent-other-1", soft: "bg-agent-other-1-soft" },
  { color: "var(--color-agent-other-2)", softColor: "var(--color-agent-other-2-soft)", text: "text-agent-other-2", bg: "bg-agent-other-2", soft: "bg-agent-other-2-soft" },
  { color: "var(--color-agent-other-3)", softColor: "var(--color-agent-other-3-soft)", text: "text-agent-other-3", bg: "bg-agent-other-3", soft: "bg-agent-other-3-soft" },
];

function overflowIndex(name: string): number {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash % OVERFLOW.length;
}

export function agentStyle(name: string): AgentStyle {
  return KNOWN[name] ?? OVERFLOW[overflowIndex(name)];
}

/** Text colour class for an agent's name. */
export function agentInk(name: string): string {
  return agentStyle(name).text;
}

/** Solid background class for an agent's dot or timeline node. */
export function agentStroke(name: string): string {
  return agentStyle(name).bg;
}

const LABELS: Record<string, string> = { ceo: "CEO", hr: "HR" };

export function agentLabel(name: string): string {
  return LABELS[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
}

/** Two-letter monogram for avatars. */
export function agentInitials(name: string): string {
  const label = agentLabel(name);
  return label.length <= 3 ? label : label.slice(0, 2);
}
