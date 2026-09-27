import { agentInk, agentLabel } from "../lib/agents";

/** An agent named in its own ink. No chip and no background: it reads as part of the sentence. */
export function AgentName({ name, className = "" }: { name: string; className?: string }) {
  return <span className={`font-semibold ${agentInk(name)} ${className}`}>{agentLabel(name)}</span>;
}
