import { agentLabel, agentTone } from "../lib/agents";

interface AgentBadgeProps {
  name: string;
  size?: "sm" | "md";
}

export function AgentBadge({ name, size = "sm" }: AgentBadgeProps) {
  const tone = agentTone(name);
  const sizing = size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2 py-1 text-sm";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border font-medium ${tone.border} ${tone.bg} ${tone.text} ${sizing}`}
    >
      <span aria-hidden className={`size-1.5 rounded-full ${tone.dot}`} />
      {agentLabel(name)}
    </span>
  );
}
