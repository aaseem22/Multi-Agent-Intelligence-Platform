import { Briefcase, Cpu, Users, Wallet, type LucideIcon } from "lucide-react";
import { agentInitials, agentInk, agentLabel, agentStyle } from "../lib/agents";

// Known agents get an icon; departments registered later fall back to their initials.
const ICONS: Record<string, LucideIcon> = { ceo: Briefcase, finance: Wallet, hr: Users, tech: Cpu };
const ICON_SIZE = { sm: 13, md: 15, lg: 20 } as const;

/** An agent's name set in its own hue, so it reads as part of the sentence. */
export function AgentName({ name, className = "" }: { name: string; className?: string }) {
  return <span className={`font-medium ${agentInk(name)} ${className}`}>{agentLabel(name)}</span>;
}

const AVATAR_SIZE = {
  sm: "size-6 rounded-[7px] text-[0.625rem]",
  md: "size-8 rounded-[9px] text-xs",
  lg: "size-11 rounded-[12px] text-sm",
} as const;

/** A tinted rounded-square monogram: the agent's mark across the whole console. */
export function AgentAvatar({ name, size = "md" }: { name: string; size?: keyof typeof AVATAR_SIZE }) {
  const style = agentStyle(name);
  const Icon = ICONS[name];
  return (
    <span
      aria-hidden
      title={agentLabel(name)}
      className={`inline-flex shrink-0 items-center justify-center font-semibold tracking-tight ${AVATAR_SIZE[size]} ${style.soft} ${style.text}`}
    >
      {Icon ? <Icon size={ICON_SIZE[size]} strokeWidth={1.9} /> : agentInitials(name)}
    </span>
  );
}

/** Avatar and name together, for lists and headers. */
export function AgentTag({ name, size = "sm", className = "" }: { name: string; size?: "sm" | "md"; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <AgentAvatar name={name} size={size} />
      <span className="font-medium text-ink">{agentLabel(name)}</span>
    </span>
  );
}
