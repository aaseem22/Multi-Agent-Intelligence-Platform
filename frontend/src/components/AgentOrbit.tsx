import { memo } from "react";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { agentLabel, agentStyle } from "../lib/agents";
import { AgentAvatar } from "./AgentName";

// A small live diagram of how the system works: the CEO dispatches to each department, and
// departments ask each other directly. Pulses travel the same routes the real agents use.

const SIZE = 320;
const C = SIZE / 2;
const NODES: Record<string, { x: number; y: number }> = {
  ceo: { x: C, y: C },
  finance: { x: C, y: 52 },
  hr: { x: 254, y: 214 },
  tech: { x: 66, y: 214 },
};

const DISPATCH = ["finance", "hr", "tech"];
// Peer routes bow outward so they never cross the CEO.
const PEERS: { from: string; to: string; bend: number }[] = [
  { from: "tech", to: "hr", bend: 46 },
  { from: "tech", to: "finance", bend: 40 },
  { from: "hr", to: "finance", bend: 40 },
];

function straight(from: string, to: string): string {
  const a = NODES[from];
  const b = NODES[to];
  return `M ${a.x} ${a.y} L ${b.x} ${b.y}`;
}

function arc(from: string, to: string, bend: number): string {
  const a = NODES[from];
  const b = NODES[to];
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  const dx = mx - C;
  const dy = my - C;
  const length = Math.hypot(dx, dy) || 1;
  const cx = mx + (dx / length) * bend;
  const cy = my + (dy / length) * bend;
  return `M ${a.x} ${a.y} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${b.x} ${b.y}`;
}

function Pulse({ path, color, delay, duration }: { path: string; color: string; delay: number; duration: number }) {
  return (
    <circle r={3.5} fill={color} stroke="var(--color-surface)" strokeWidth={1.5} opacity={0}>
      <animateMotion dur={`${duration}s`} begin={`${delay}s`} repeatCount="indefinite" path={path} keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.45 0 0.2 1" />
      <animate attributeName="opacity" dur={`${duration}s`} begin={`${delay}s`} repeatCount="indefinite" values="0;1;1;0" keyTimes="0;0.1;0.85;1" />
    </circle>
  );
}

export const AgentOrbit = memo(function AgentOrbit() {
  const reduced = useReducedMotion();
  return (
    <figure className="relative mx-auto aspect-square w-full max-w-[320px]" aria-label="The CEO agent dispatches work to Finance, HR and Tech, which also ask each other directly.">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="absolute inset-0 h-full w-full" aria-hidden>
        <circle cx={C} cy={C} r={124} fill="none" stroke="var(--color-line-strong)" strokeDasharray="2 6" className={reduced ? "" : "origin-center animate-spin-slow"} style={{ transformBox: "fill-box" }} />
        <circle cx={C} cy={C} r={62} fill="none" stroke="var(--color-line)" />

        {DISPATCH.map((agent) => (
          <path key={agent} d={straight("ceo", agent)} stroke="var(--color-line-strong)" strokeWidth={1.5} strokeDasharray="4 5" fill="none" />
        ))}
        {PEERS.map(({ from, to, bend }) => (
          <path key={`${from}-${to}`} d={arc(from, to, bend)} stroke="var(--color-accent)" strokeOpacity={0.45} strokeWidth={1.5} fill="none" />
        ))}

        {reduced
          ? null
          : [
              ...DISPATCH.map((agent, i) => (
                <Pulse key={`d-${agent}`} path={straight("ceo", agent)} color="var(--color-ink)" delay={i * 0.6} duration={2.4} />
              )),
              ...PEERS.map(({ from, to, bend }, i) => (
                <Pulse key={`p-${from}-${to}`} path={arc(from, to, bend)} color="var(--color-accent)" delay={1.2 + i * 0.9} duration={2.8} />
              )),
            ]}
      </svg>

      {Object.entries(NODES).map(([agent, point]) => {
        const isCeo = agent === "ceo";
        return (
          <div
            key={agent}
            className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1.5"
            style={{ left: `${(point.x / SIZE) * 100}%`, top: `${(point.y / SIZE) * 100}%` }}
          >
            {isCeo ? (
              <span className="relative inline-flex size-14 items-center justify-center rounded-2xl bg-ink text-on-ink shadow-raised">
                <span aria-hidden className={`absolute inset-0 rounded-2xl ${reduced ? "" : "animate-pulse-dot"}`} />
                <span className="text-sm font-semibold tracking-tight">CEO</span>
              </span>
            ) : (
              <span className="rounded-[14px] bg-surface p-1 shadow-raised ring-1 ring-line">
                <AgentAvatar name={agent} size="lg" />
              </span>
            )}
            {isCeo ? null : (
              <span className="rounded-full bg-surface/80 px-2 py-0.5 text-2xs font-medium ring-1 ring-line backdrop-blur" style={{ color: agentStyle(agent).color }}>
                {agentLabel(agent)}
              </span>
            )}
          </div>
        );
      })}
    </figure>
  );
});
