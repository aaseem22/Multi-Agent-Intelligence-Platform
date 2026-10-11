import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { ObsEdge, ObservabilitySummary } from "../types/observability";
import { useReducedMotion } from "./hooks";
import { Panel } from "./Panel";
import { agentHue, agentName, agentSoftHue, formatAgo, formatInt } from "./theme";

const TASK_STROKE = "var(--color-faint)";

const W = 560;
const H = 430;
const CX = W / 2;
const CY = H / 2 + 8;
const ORBIT_RX = 172;
const ORBIT_RY = 132;
const NODE_R = 32;
const CORE_R = 42;
const RECENT_MS = 24 * 3_600_000;

interface Point {
  x: number;
  y: number;
}

interface EdgeGeometry {
  key: string;
  edge: ObsEdge;
  refused: boolean;
  path: string;
  mid: Point;
  width: number;
  recent: boolean;
}

function layout(agents: string[]): Map<string, Point> {
  const points = new Map<string, Point>();
  agents.forEach((agent, i) => {
    const angle = -Math.PI / 2 + (i / agents.length) * Math.PI * 2;
    points.set(agent, { x: CX + Math.cos(angle) * ORBIT_RX, y: CY + Math.sin(angle) * ORBIT_RY });
  });
  return points;
}

/** Point on the segment a->b, `inset` px in from a. */
function inset(a: Point, b: Point, by: number): Point {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy) || 1;
  return { x: a.x + (dx / length) * by, y: a.y + (dy / length) * by };
}

function curve(a: Point, b: Point, bend: number): { path: string; mid: Point } {
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy) || 1;
  // Always bow away from the core so peer traffic never crosses the supervisor.
  let px = dy / length;
  let py = -dx / length;
  if (px * (mx - CX) + py * (my - CY) < 0) {
    px = -px;
    py = -py;
  }
  const control = { x: mx + px * bend, y: my + py * bend };
  const start = inset(a, control, NODE_R + 4);
  const end = inset(b, control, NODE_R + 9);
  const mid = {
    x: 0.25 * start.x + 0.5 * control.x + 0.25 * end.x,
    y: 0.25 * start.y + 0.5 * control.y + 0.25 * end.y,
  };
  const f = (n: number) => n.toFixed(1);
  return { path: `M ${f(start.x)} ${f(start.y)} Q ${f(control.x)} ${f(control.y)} ${f(end.x)} ${f(end.y)}`, mid };
}

function geometry(summary: ObservabilitySummary, points: Map<string, Point>, supervisor: string): EdgeGeometry[] {
  const core = { x: CX, y: CY };
  const maxCount = Math.max(1, ...summary.edges.map((e) => e.count));
  const endMs = summary.window ? Date.parse(summary.window.end) : Date.now();
  const result: EdgeGeometry[] = [];
  for (const edge of summary.edges) {
    const from = edge.source === supervisor ? core : points.get(edge.source);
    const to = edge.target === supervisor ? core : points.get(edge.target);
    if (!from || !to) continue;
    const recent = edge.last_at != null && endMs - Date.parse(edge.last_at) < RECENT_MS;
    if (edge.count > 0) {
      const width = 1.2 + 3.3 * Math.sqrt(edge.count / maxCount);
      if (edge.kind === "task") {
        const start = inset(from, to, CORE_R + 6);
        const end = inset(to, from, NODE_R + 8);
        result.push({
          key: `task:${edge.source}:${edge.target}`,
          edge,
          refused: false,
          path: `M ${start.x.toFixed(1)} ${start.y.toFixed(1)} L ${end.x.toFixed(1)} ${end.y.toFixed(1)}`,
          mid: { x: start.x + (end.x - start.x) * 0.45, y: start.y + (end.y - start.y) * 0.45 },
          width,
          recent,
        });
      } else {
        // The alphabetically first direction hugs the chord; the reverse flies a wider arc.
        const { path, mid } = curve(from, to, edge.source < edge.target ? 34 : 64);
        result.push({ key: `peer:${edge.source}:${edge.target}`, edge, refused: false, path, mid, width, recent });
      }
    }
    if (edge.refusals > 0) {
      const { path, mid } = curve(from, to, edge.source < edge.target ? 100 : 146);
      result.push({ key: `refused:${edge.source}:${edge.target}`, edge, refused: true, path, mid, width: 1.6, recent });
    }
  }
  return result;
}

function describe(g: EdgeGeometry): string {
  const { edge } = g;
  const route = `${agentName(edge.source)} to ${agentName(edge.target)}`;
  if (g.refused) return `${route}: ${edge.refusals} peer ${edge.refusals === 1 ? "call" : "calls"} refused by the guards`;
  if (edge.kind === "task") return `${route}: ${edge.count} dispatched ${edge.count === 1 ? "subtask" : "subtasks"}`;
  return `${route}: ${edge.count} peer ${edge.count === 1 ? "call" : "calls"}`;
}

// The SVG scales with its panel; on narrow screens labels would shrink below legibility,
// so text grows by the inverse of the scale (capped) to stay near its intended pixel size.
function useLabelScale(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(W);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width || W));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, Math.min(Math.max((W / width) * 0.75, 1), 1.3)];
}

function ConstellationImpl({ summary }: { summary: ObservabilitySummary }) {
  const reduced = useReducedMotion();
  const [hovered, setHovered] = useState<string | null>(null);
  const [frameRef, k] = useLabelScale();
  const supervisor = summary.supervisor ?? "ceo";

  const { agents, points, edges, stats } = useMemo(() => {
    const names = new Set<string>();
    for (const row of summary.per_agent) if (row.agent !== supervisor) names.add(row.agent);
    for (const edge of summary.edges) {
      if (edge.source !== supervisor) names.add(edge.source);
      if (edge.target !== supervisor) names.add(edge.target);
    }
    const agentList = [...names].sort();
    const pointMap = layout(agentList);
    return {
      agents: agentList,
      points: pointMap,
      edges: geometry(summary, pointMap, supervisor),
      stats: new Map(summary.per_agent.map((row) => [row.agent, row])),
    };
  }, [summary, supervisor]);

  const hoveredEdge = edges.find((e) => e.key === hovered) ?? null;
  const supervisorStats = stats.get(supervisor);
  const peerRoutes = summary.edges
    .filter((e) => e.kind === "peer")
    .toSorted((a, b) => b.count + b.refusals - (a.count + a.refusals));

  return (
    <Panel
      title="Agent network"
      labelId="obs-constellation"
      meta={`${formatInt(summary.peer_calls)} peer calls, ${formatInt(summary.refusals)} refused`}
      className="obs-area-constellation"
    >
      <div className="relative" ref={frameRef}>
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-labelledby="obs-constellation-desc">
          <desc id="obs-constellation-desc">
            {edges.map(describe).join(". ") || "No agent traffic in this window."}
          </desc>
          <defs>
            <marker id="obs-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--obs-ice)" />
            </marker>
            <marker id="obs-arrow-dim" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill={TASK_STROKE} />
            </marker>
            <marker id="obs-arrow-alert" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--obs-alert)" />
            </marker>
          </defs>

          <g aria-hidden>
            <ellipse cx={CX} cy={CY} rx={ORBIT_RX} ry={ORBIT_RY} fill="none" stroke="var(--obs-line)" strokeDasharray="1 5" />
            <ellipse cx={CX} cy={CY} rx={ORBIT_RX * 0.5} ry={ORBIT_RY * 0.5} fill="none" stroke="var(--obs-line)" strokeOpacity={0.6} />
          </g>

          {edges.map((g) => {
            const active = hovered === g.key;
            const dim = hovered !== null && !active;
            const stroke = g.refused ? "var(--obs-alert)" : g.edge.kind === "task" ? TASK_STROKE : "var(--obs-ice)";
            const marker = g.refused ? "url(#obs-arrow-alert)" : g.edge.kind === "task" ? "url(#obs-arrow-dim)" : "url(#obs-arrow)";
            return (
              <g key={g.key} opacity={dim ? 0.3 : 1} style={{ transition: "opacity 150ms" }}>
                <path
                  d={g.path}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={active ? g.width + 1 : g.width}
                  strokeOpacity={g.edge.kind === "task" && !g.refused ? 0.85 : 1}
                  strokeDasharray={g.refused ? "5 5" : undefined}
                  strokeLinecap="round"
                  markerEnd={marker}
                />
                {g.recent && !reduced && !g.refused ? (
                  <circle r={g.edge.kind === "task" ? 2.5 : 3.5} fill={g.edge.kind === "task" ? TASK_STROKE : "var(--obs-ice)"} stroke="var(--color-surface)" strokeWidth={1.5}>
                    <animateMotion dur={g.edge.kind === "task" ? "3.2s" : "2.2s"} repeatCount="indefinite" path={g.path} />
                  </circle>
                ) : null}
                {g.refused ? (
                  <g transform={`translate(${g.mid.x.toFixed(1)} ${g.mid.y.toFixed(1)})`}>
                    <circle r={8} fill="var(--obs-panel)" stroke="var(--obs-alert)" strokeWidth={1.5} />
                    <line x1={-5} y1={5} x2={5} y2={-5} stroke="var(--obs-alert)" strokeWidth={1.5} />
                  </g>
                ) : (
                  <text
                    x={g.mid.x + (g.edge.kind === "task" ? 12 : 0)}
                    y={g.mid.y}
                    dy={g.edge.kind === "task" ? 4 : -6}
                    textAnchor="middle"
                    className="obs-mono"
                    fontSize={12 * k}
                    fill={g.edge.kind === "task" ? "var(--obs-text-3)" : "var(--obs-text)"}
                    paintOrder="stroke"
                    stroke="var(--obs-panel)"
                    strokeWidth={4}
                  >
                    {g.edge.count}
                  </text>
                )}
                <path
                  d={g.path}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={16}
                  tabIndex={0}
                  role="button"
                  aria-label={describe(g)}
                  onPointerEnter={() => setHovered(g.key)}
                  onPointerLeave={() => setHovered(null)}
                  onFocus={() => setHovered(g.key)}
                  onBlur={() => setHovered(null)}
                  style={{ cursor: "default", outline: "none" }}
                />
              </g>
            );
          })}

          <g>
            <circle cx={CX} cy={CY} r={CORE_R + 8} fill="none" stroke="var(--obs-line-strong)" strokeWidth={1} strokeDasharray="3 4" />
            <circle cx={CX} cy={CY} r={CORE_R} fill="var(--color-ink)" />
            <text x={CX} y={CY + 1} textAnchor="middle" fontSize={15 * k} fontWeight={600} fill="var(--color-on-ink)">
              {agentName(supervisor)}
            </text>
            <text x={CX} y={CY + 15} textAnchor="middle" fontSize={9.5 * k} fill="var(--color-on-ink)" fillOpacity={0.7} className="obs-mono">
              {supervisorStats ? `${supervisorStats.runs} plans` : "supervisor"}
            </text>
          </g>

          {agents.map((agent) => {
            const point = points.get(agent)!;
            const hue = agentHue(agent, supervisor);
            const row = stats.get(agent);
            // Labels sit radially outside the orbit, away from every edge.
            const angle = Math.atan2((point.y - CY) / ORBIT_RY, (point.x - CX) / ORBIT_RX);
            const lx = point.x + Math.cos(angle) * (NODE_R + 14);
            const ly = point.y + Math.sin(angle) * (NODE_R + 14) + 4;
            const anchor = Math.abs(Math.cos(angle)) < 0.35 ? "middle" : Math.cos(angle) > 0 ? "start" : "end";
            const vertical = Math.abs(Math.cos(angle)) < 0.35;
            const labelX = vertical ? point.x + NODE_R + 10 : lx;
            const labelY = vertical ? point.y + 4 : ly + 8;
            return (
              <g key={agent}>
                <circle cx={point.x} cy={point.y} r={NODE_R + 6} fill="none" stroke={hue} strokeOpacity={0.25} />
                <circle cx={point.x} cy={point.y} r={NODE_R} fill={agentSoftHue(agent, supervisor)} stroke={hue} strokeWidth={1.75} />
                <text x={point.x} y={point.y + 4} textAnchor="middle" fontSize={12 * k} fontWeight={600} fill={hue}>
                  {agentName(agent)}
                </text>
                <text x={labelX} y={labelY} textAnchor={vertical ? "start" : anchor} fontSize={11 * k}>
                  <tspan fill="var(--obs-text-2)">{row ? `${row.runs} runs` : "no runs"}</tspan>
                  {row && row.failures > 0 ? <tspan fill="var(--obs-alert)">{`  ${row.failures} failed`}</tspan> : null}
                </text>
              </g>
            );
          })}
        </svg>

        {hoveredEdge ? (
          <div
            className="obs-tooltip"
            role="status"
            style={{
              left: `${(hoveredEdge.mid.x / W) * 100}%`,
              top: `${(hoveredEdge.mid.y / H) * 100}%`,
              transform: "translate(-50%, calc(-100% - 14px))",
            }}
          >
            <p className="font-medium">
              {agentName(hoveredEdge.edge.source)} <span className="obs-t3">to</span> {agentName(hoveredEdge.edge.target)}
            </p>
            <p className="obs-mono text-xs obs-t2">
              {hoveredEdge.refused
                ? `${hoveredEdge.edge.refusals} refused by guards`
                : hoveredEdge.edge.kind === "task"
                  ? `${hoveredEdge.edge.count} subtasks dispatched`
                  : `${hoveredEdge.edge.count} peer calls`}
            </p>
            {hoveredEdge.edge.last_at ? (
              <p className="obs-mono text-xs obs-t3">last {formatAgo(hoveredEdge.edge.last_at)}</p>
            ) : null}
          </div>
        ) : null}
      </div>

      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted" aria-label="Legend">
        <li className="flex items-center gap-2">
          <svg width="26" height="8" aria-hidden><line x1="1" y1="4" x2="25" y2="4" stroke={TASK_STROKE} strokeWidth="2" /></svg>
          Subtask dispatched
        </li>
        <li className="flex items-center gap-2">
          <svg width="26" height="8" aria-hidden><line x1="1" y1="4" x2="25" y2="4" stroke="var(--obs-ice)" strokeWidth="3" /></svg>
          Peer call (thicker is more)
        </li>
        <li className="flex items-center gap-2">
          <svg width="26" height="8" aria-hidden><line x1="1" y1="4" x2="25" y2="4" stroke="var(--obs-alert)" strokeWidth="1.6" strokeDasharray="5 4" /></svg>
          Refused by guards
        </li>
        {!reduced ? (
          <li className="flex items-center gap-2">
            <svg width="10" height="10" aria-hidden><circle cx="5" cy="5" r="3.5" fill="var(--obs-ice)" /></svg>
            Traffic in the last 24 h
          </li>
        ) : null}
      </ul>

      {peerRoutes.length ? (
        <table className="mt-4 w-full border-t border-line text-left text-sm">
          <caption className="pt-3 pb-1.5 text-left text-xs font-medium text-muted">Peer routes</caption>
          <thead className="sr-only">
            <tr>
              <th>Route</th>
              <th>Calls</th>
              <th>Refused</th>
              <th>Last call</th>
            </tr>
          </thead>
          <tbody>
            {peerRoutes.map((edge) => (
              <tr key={`${edge.source}:${edge.target}`} className="border-t border-line">
                <th scope="row" className="py-1.5 pr-3 font-medium whitespace-nowrap text-ink">
                  {agentName(edge.source)} <span className="obs-ice">→</span> {agentName(edge.target)}
                </th>
                <td className="obs-mono obs-t1 py-1.5 pr-3 text-right">{edge.count}</td>
                <td className={`py-1.5 pr-3 text-right text-xs whitespace-nowrap ${edge.refusals ? "text-danger" : "text-faint"}`}>
                  {edge.refusals ? `${edge.refusals} refused` : "-"}
                </td>
                <td className="py-1.5 text-right text-xs whitespace-nowrap text-muted">{formatAgo(edge.last_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </Panel>
  );
}

export const Constellation = memo(ConstellationImpl);
