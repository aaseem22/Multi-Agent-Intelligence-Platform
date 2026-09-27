import { ExternalLink, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ObsA2AMessage, ObsObservation, ObsTraceScore, ObservabilityTraceDetail } from "../types/observability";
import { useTraceDetail } from "./hooks";
import { StatusMark } from "./TraceFeed";
import { agentHue, agentName, formatCompact, formatCost, formatSeconds, formatStamp, scoreLabel } from "./theme";

const KIND_STYLE = {
  a2a: { glyph: "⇄", label: "Peer call (a2a span)" },
  agent: { glyph: "◆", label: "Agent run" },
  llm: { glyph: "◇", label: "Model call" },
  tool: { glyph: "▸", label: "Tool call" },
  span: { glyph: "·", label: "Graph step" },
  event: { glyph: "•", label: "Event" },
} as const;

const LLM_COLOR = "#6d8fb3";
const TOOL_COLOR = "#a9bccb";
const SPAN_COLOR = "#2f4b66";

function agentOf(obs: ObsObservation): string | null {
  const meta = obs.metadata.agent;
  if (typeof meta === "string") return meta;
  if (obs.name.startsWith("agent:")) return obs.name.slice(6);
  return null;
}

function isWarning(obs: ObsObservation): boolean {
  return obs.failed || obs.level === "ERROR" || obs.level === "WARNING" || Boolean(obs.status_message);
}

function barColor(obs: ObsObservation, supervisor: string | null): string {
  if (obs.level === "ERROR" || obs.failed) return "var(--obs-alert)";
  if (obs.kind === "a2a") return "var(--obs-ice)";
  if (obs.kind === "agent") return agentHue(agentOf(obs) ?? "", supervisor);
  if (obs.kind === "llm") return LLM_COLOR;
  if (obs.kind === "tool") return obs.status_message ? "var(--obs-alert)" : TOOL_COLOR;
  return SPAN_COLOR;
}

function niceStep(totalMs: number): number {
  const target = totalMs / 6;
  const steps = [100, 250, 500, 1000, 2000, 5000, 10_000, 15_000, 20_000, 30_000, 60_000, 120_000, 300_000];
  return steps.find((s) => s >= target) ?? 600_000;
}

function A2ALabel({ obs }: { obs: ObsObservation }) {
  const [sender, recipient] = obs.name.replace(/^a2a:/, "").split("->");
  const hop = obs.metadata.hop_count;
  const chain = Array.isArray(obs.metadata.chain) ? (obs.metadata.chain as string[]) : [];
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2">
      <span className="obs-cond font-semibold text-(--obs-text)">
        {agentName(sender ?? "")} <span className="obs-ice">→</span> {agentName(recipient ?? "")}
      </span>
      {typeof hop === "number" ? (
        <span className="obs-mono border border-(--obs-ice-dim) px-1 text-2xs leading-4 obs-ice">hop {hop}</span>
      ) : null}
      {chain.length ? <span className="obs-mono obs-t3 text-2xs">via {chain.map(agentName).join(" › ")}</span> : null}
    </span>
  );
}

function Waterfall({ detail, supervisor }: { detail: ObservabilityTraceDetail; supervisor: string | null }) {
  const [showSteps, setShowSteps] = useState(true);
  const { rows, t0, total, ticks } = useMemo(() => {
    const starts = detail.observations.map((o) => (o.start ? Date.parse(o.start) : NaN)).filter((n) => !Number.isNaN(n));
    const ends = detail.observations.map((o) => (o.end ? Date.parse(o.end) : NaN)).filter((n) => !Number.isNaN(n));
    const first = starts.length ? Math.min(...starts) : 0;
    const last = ends.length ? Math.max(...ends) : first + 1;
    const span = Math.max(last - first, 1);
    const step = niceStep(span);
    const tickList: number[] = [];
    for (let t = 0; t <= span; t += step) tickList.push(t);
    return { rows: detail.observations, t0: first, total: span, ticks: tickList };
  }, [detail.observations]);

  const visible = showSteps ? rows : rows.filter((o) => o.kind !== "span" || o.depth === 0);

  return (
    <section aria-labelledby="obs-waterfall-title">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-3">
        <h3 id="obs-waterfall-title" className="obs-panel-title">
          Timeline
        </h3>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs obs-t2">
          {(["agent", "a2a", "llm", "tool", "span"] as const).map((kind) => (
            <span key={kind} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="obs-mono obs-t3">{KIND_STYLE[kind].glyph}</span>
              {KIND_STYLE[kind].label}
            </span>
          ))}
          <button type="button" className="obs-button !py-1 !text-xs" aria-pressed={!showSteps} onClick={() => setShowSteps((v) => !v)}>
            {showSteps ? "Hide graph steps" : "Show graph steps"}
          </button>
        </div>
      </div>

      <div role="table" aria-label="Observations in this trace" className="text-sm">
        <div role="row" className="obs-waterfall-row !min-h-6 !border-t-0">
          <span role="columnheader" className="obs-cond obs-t3 text-xs">Observation</span>
          <span role="columnheader" className="relative h-5">
            <span className="sr-only">Timeline</span>
            {ticks.map((t) => (
              <span
                key={t}
                aria-hidden
                className={`obs-mono obs-t3 absolute top-0 text-2xs whitespace-nowrap ${t === 0 ? "" : t / total > 0.92 ? "-translate-x-full" : "-translate-x-1/2"}`}
                style={{ left: `${(t / total) * 100}%` }}
              >
                {t === 0 ? "0" : formatSeconds(t, t < 1000 ? 1 : 0)}
              </span>
            ))}
          </span>
          <span role="columnheader" className="obs-cond obs-t3 text-right text-xs">Duration</span>
        </div>
        {visible.map((obs) => {
          const start = obs.start ? Date.parse(obs.start) - t0 : 0;
          const duration = obs.latency_ms ?? 0;
          const left = (start / total) * 100;
          const width = Math.max((duration / total) * 100, 0.3);
          const warn = isWarning(obs);
          const heavy = obs.kind === "agent" || obs.kind === "a2a";
          const color = barColor(obs, supervisor);
          return (
            <div
              role="row"
              key={obs.id}
              className={`obs-waterfall-row ${obs.kind === "a2a" ? "obs-waterfall-row--a2a" : ""} ${warn ? "obs-waterfall-row--warn" : ""}`}
            >
              <div role="cell" className="flex min-w-0 items-start gap-1.5 py-1 pr-3" style={{ paddingLeft: obs.depth * 14 }}>
                <span
                  aria-hidden
                  className="obs-mono w-3 shrink-0 text-center"
                  style={{ color: obs.kind === "agent" ? color : obs.kind === "a2a" ? "var(--obs-ice)" : "var(--obs-text-3)" }}
                >
                  {KIND_STYLE[obs.kind].glyph}
                </span>
                <span className="min-w-0">
                  {obs.kind === "a2a" ? (
                    <A2ALabel obs={obs} />
                  ) : (
                    <span className={`block truncate ${heavy ? "obs-cond font-semibold text-(--obs-text)" : obs.kind === "span" ? "obs-t3" : "obs-t2"} ${obs.kind === "tool" || obs.kind === "llm" ? "obs-mono text-xs" : ""}`}>
                      {obs.kind === "agent" ? agentName(agentOf(obs) ?? obs.name) : obs.kind === "llm" ? (obs.model ?? obs.name) : obs.name}
                      {obs.kind === "agent" && obs.metadata.mode === "peer" ? <span className="obs-t3 font-normal"> peer mode</span> : null}
                      {obs.kind === "llm" && obs.tokens ? <span className="obs-t3"> {formatCompact(obs.tokens)} tok</span> : null}
                    </span>
                  )}
                  {obs.status_message ? (
                    <span className="obs-mono obs-alert block text-2xs leading-4 break-words">
                      {obs.level === "ERROR" || obs.failed ? "✕ " : "⊘ "}
                      {obs.status_message}
                    </span>
                  ) : null}
                </span>
              </div>
              <div role="cell" className="relative h-full min-h-6">
                {ticks.map((t) => (
                  <span key={t} aria-hidden className="absolute inset-y-0 w-px bg-(--obs-line)/50" style={{ left: `${(t / total) * 100}%` }} />
                ))}
                <span
                  className="absolute top-1/2 -translate-y-1/2 rounded-r-[3px]"
                  title={`${obs.name}: ${formatSeconds(duration)}${obs.tokens ? `, ${obs.tokens} tokens` : ""}`}
                  style={{
                    left: `${left}%`,
                    width: `${width}%`,
                    minWidth: 2,
                    height: heavy ? 10 : obs.kind === "span" ? 4 : 7,
                    background: color,
                    boxShadow: obs.kind === "a2a" ? "0 0 10px rgba(127,220,255,0.7)" : heavy ? `0 0 6px ${color}66` : undefined,
                  }}
                />
              </div>
              <div role="cell" className="obs-mono text-right text-xs whitespace-nowrap obs-t2">
                {formatSeconds(duration)}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ScoreGrid({ scores }: { scores: ObsTraceScore[] }) {
  if (!scores.length) return <p className="obs-t3 text-sm">No eval scores were recorded for this trace.</p>;
  const names = [...new Set(scores.map((s) => s.name ?? "score"))].sort();
  const agents = [...new Set(scores.map((s) => s.agent ?? "trace"))].sort();
  const lookup = new Map(scores.map((s) => [`${s.agent ?? "trace"}|${s.name ?? "score"}`, s]));
  return (
    <table className="w-full text-left text-sm">
      <caption className="sr-only">Eval scores by agent and stage</caption>
      <thead>
        <tr className="obs-cond obs-t3 text-xs">
          <th className="py-1 pr-4 font-normal">Agent</th>
          {names.map((n) => (
            <th key={n} className="py-1 pr-4 font-normal">
              {scoreLabel(n)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {agents.map((agent) => (
          <tr key={agent} className="border-t border-(--obs-line)">
            <th scope="row" className="obs-cond py-1.5 pr-4 font-semibold">
              {agentName(agent)}
            </th>
            {names.map((n) => {
              const s = lookup.get(`${agent}|${n}`);
              if (!s) return <td key={n} className="obs-t3 py-1.5 pr-4">–</td>;
              return (
                <td key={n} className="py-1.5 pr-4" title={s.comment ?? undefined}>
                  <span className={`obs-cond inline-flex items-center gap-1 ${s.passed ? "obs-ok" : "obs-amber"}`}>
                    <span aria-hidden>{s.passed ? "✓" : "✕"}</span>
                    {s.passed ? "Passed" : "Failed"}
                  </span>
                  {!s.passed && s.comment ? <span className="obs-t3 block text-xs">{s.comment}</span> : null}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PeerMessages({ messages }: { messages: ObsA2AMessage[] }) {
  if (!messages.length) return <p className="obs-t3 text-sm">No agent asked a peer during this request.</p>;
  return (
    <ol className="space-y-2.5">
      {messages.map((m) => (
        <li key={m.id} className={`border-l-2 pl-3 ${m.refused ? "border-(--obs-alert)" : m.type === "peer_response" ? "border-(--obs-line-strong)" : "border-(--obs-ice)"}`}>
          <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <span className="obs-cond font-semibold">
              {agentName(m.sender)} <span className={m.refused ? "obs-alert" : "obs-ice"}>→</span> {agentName(m.recipient)}
            </span>
            <span className="obs-mono obs-t3 text-2xs">
              {m.type === "peer_response" ? "response" : "request"}, hop {m.hop_count}
            </span>
            {m.refused ? <span className="obs-cond obs-alert text-xs">⊘ Refused</span> : null}
          </p>
          <p className="obs-t2 mt-0.5 text-sm">{m.content}</p>
          {m.reason ? <p className="obs-mono obs-alert mt-0.5 text-xs">{m.reason}</p> : null}
        </li>
      ))}
    </ol>
  );
}

export function TraceInspector({
  traceId,
  onClose,
  supervisor,
}: {
  traceId: string;
  onClose: () => void;
  supervisor: string | null;
}) {
  const [state, retry] = useTraceDetail(traceId);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  const detail = state.status === "ready" ? state.detail : null;
  const trace = detail?.trace ?? null;

  return (
    <>
      <div className="obs-drawer-backdrop" onClick={onClose} aria-hidden />
      <div className="obs-drawer" role="dialog" aria-modal="true" aria-labelledby="obs-inspector-title">
        <header className="flex items-start gap-4 border-b border-(--obs-line) px-5 py-4 md:px-7">
          <div className="min-w-0 flex-1">
            <p className="obs-mono obs-t3 text-2xs">trace {traceId.slice(0, 12)}…</p>
            <h2 id="obs-inspector-title" className="obs-cond mt-1 text-xl leading-snug font-medium text-(--obs-text) md:text-2xl">
              {trace?.question ?? (state.status === "error" ? "Trace unavailable" : "Loading trace")}
            </h2>
            {trace ? (
              <dl className="mt-2.5 flex flex-wrap whitespace-nowrap items-center gap-x-5 gap-y-1.5 text-sm">
                <div><dt className="sr-only">Status</dt><dd><StatusMark status={trace.status} /></dd></div>
                <div className="flex gap-1.5"><dt className="obs-t3">Started</dt><dd className="obs-mono obs-t1">{formatStamp(trace.timestamp)}</dd></div>
                <div className="flex gap-1.5"><dt className="obs-t3">Latency</dt><dd className="obs-mono obs-t1">{formatSeconds(trace.latency_ms)}</dd></div>
                <div className="flex gap-1.5"><dt className="obs-t3">Tokens</dt><dd className="obs-mono obs-t1">{formatCompact(trace.tokens)}</dd></div>
                <div className="flex gap-1.5"><dt className="obs-t3">Cost</dt><dd className="obs-mono obs-t1">{formatCost(trace.cost)}</dd></div>
                {trace.session_id ? (
                  <div className="flex gap-1.5"><dt className="obs-t3">Session</dt><dd className="obs-mono obs-t2 max-w-[16ch] truncate">{trace.session_id}</dd></div>
                ) : null}
              </dl>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {trace ? (
              <a href={trace.url} target="_blank" rel="noreferrer" className="obs-button obs-button--primary">
                <span className="hidden sm:inline">Open in Langfuse</span>
                <span className="sm:hidden">Langfuse</span>
                <ExternalLink size={14} aria-hidden />
              </a>
            ) : null}
            <button ref={closeRef} type="button" onClick={onClose} className="obs-button !px-2" aria-label="Close trace inspector">
              <X size={16} aria-hidden />
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-7">
          {state.status === "loading" ? (
            <div role="status" className="flex items-center gap-3 py-10">
              <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden className="obs-sweep-fast">
                <circle cx="14" cy="14" r="11" fill="none" stroke="var(--obs-line-strong)" strokeWidth="2" />
                <path d="M14 3 A11 11 0 0 1 25 14" fill="none" stroke="var(--obs-ice)" strokeWidth="2" strokeLinecap="round" />
              </svg>
              <span className="obs-cond obs-t2">Reading observations from Langfuse</span>
            </div>
          ) : state.status === "error" ? (
            <div role="alert" className="border-l-2 border-(--obs-alert) py-1 pl-4">
              <p className="obs-cond obs-alert font-semibold">Could not load this trace</p>
              <p className="obs-t2 mt-1 text-sm">{state.error}</p>
              <button type="button" onClick={retry} className="obs-button mt-3">Try again</button>
            </div>
          ) : !detail?.enabled || !trace ? (
            <p className="obs-t2 text-sm">{detail?.reason ?? "Langfuse did not return this trace."}</p>
          ) : (
            <div className="space-y-8">
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                <span className="obs-t3">Agents</span>
                {trace.agents.map((a) => (
                  <span key={a} className="obs-cond inline-flex items-center gap-1.5">
                    <span aria-hidden className="size-2 rounded-full" style={{ background: agentHue(a, supervisor) }} />
                    {agentName(a)}
                  </span>
                ))}
              </div>
              <Waterfall detail={detail} supervisor={supervisor} />
              <div className="grid gap-8 lg:grid-cols-2">
                <section aria-labelledby="obs-scores-title">
                  <h3 id="obs-scores-title" className="obs-panel-title mb-2">Eval scores</h3>
                  <ScoreGrid scores={detail.scores} />
                </section>
                <section aria-labelledby="obs-peers-title">
                  <h3 id="obs-peers-title" className="obs-panel-title mb-2">Peer messages</h3>
                  <PeerMessages messages={detail.a2a} />
                </section>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
