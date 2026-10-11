import { ArrowUpRight, Bot, Database, Lock, Network, Sparkles, Waypoints, type LucideIcon } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { backend } from "../api/backend";
import { AgentAvatar } from "../components/AgentName";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { chatHref } from "../hooks/useHashRoute";
import { useResource } from "../hooks/useResource";
import { agentLabel, agentStyle } from "../lib/agents";
import { PREFILL_KEY } from "../lib/prefill";
import type { AgentCard, Skill } from "../types/contracts";

const fetchAgents = (signal: AbortSignal) => backend.getAgents(signal);

/** "budget_vs_actual" -> "Budget vs actual". */
function humanise(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Opens the chat with the question already typed in, ready to send. */
function askInChat(question: string): void {
  try {
    window.sessionStorage.setItem(PREFILL_KEY, question);
  } catch {
    // Without storage the chat simply opens empty.
  }
  window.location.hash = chatHref(null);
}

function Stat({ icon: Icon, label, value, index }: { icon: LucideIcon; label: string; value: number; index: number }) {
  return (
    <div className="card flex items-center gap-3.5 px-4 py-3.5 stagger" style={{ "--i": index } as CSSProperties}>
      <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-subtle text-ink-2">
        <Icon aria-hidden size={18} strokeWidth={1.75} />
      </span>
      <div className="min-w-0">
        <p className="text-2xl leading-none font-semibold tracking-tight text-ink tabular-nums">{value}</p>
        <p className="mt-1 truncate text-xs text-muted">{label}</p>
      </div>
    </div>
  );
}

function Summary({ cards }: { cards: AgentCard[] }) {
  const departments = cards.filter((card) => card.accepts_peer_requests).length;
  const skills = cards.reduce((sum, card) => sum + card.skills.length, 0);
  const sources = new Set(cards.flatMap((card) => card.owned_data)).size;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat icon={Bot} label="Registered agents" value={cards.length} index={1} />
      <Stat icon={Network} label="Departments that answer peers" value={departments} index={2} />
      <Stat icon={Sparkles} label="Skills" value={skills} index={3} />
      <Stat icon={Database} label="Owned data sources" value={sources} index={4} />
    </div>
  );
}

// --- Team structure ------------------------------------------------------------------------------

function MapNode({ card, selected, onSelect }: { card: AgentCard; selected: boolean; onSelect: () => void }) {
  const style = agentStyle(card.name);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`group relative flex h-full w-full flex-col items-center rounded-card border bg-surface px-3 pt-4 pb-3.5 text-center transition-[border-color,box-shadow,transform] duration-300 ease-out-soft hover:-translate-y-0.5 hover:shadow-raised ${
        selected ? "shadow-raised" : "border-line shadow-card"
      }`}
      style={selected ? { borderColor: style.color, boxShadow: `0 0 0 3px ${style.softColor}, var(--shadow-raised)` } : undefined}
    >
      <AgentAvatar name={card.name} size="lg" />
      <span className="mt-2.5 text-base font-semibold text-ink">{agentLabel(card.name)}</span>
      <span className="text-xs text-muted">{card.department}</span>
      <span className="mt-2.5 flex min-h-5 flex-wrap justify-center gap-1">
        {card.owned_data.length === 0 ? (
          <span className="text-2xs text-faint">Owns no domain data</span>
        ) : (
          card.owned_data.map((item) => (
            <span key={item} className="mono-tag h-5! text-[0.625rem]!">
              {item}
            </span>
          ))
        )}
      </span>
    </button>
  );
}

/** The supervisor on top, departments below, and the peer channel between departments. */
function TeamMap({
  supervisors,
  departments,
  selected,
  onSelect,
}: {
  supervisors: AgentCard[];
  departments: AgentCard[];
  selected: string;
  onSelect: (name: string) => void;
}) {
  const columns = Math.min(Math.max(departments.length, 1), 4);
  return (
    <section aria-labelledby="team-map" className="card relative overflow-hidden px-5 pt-5 pb-6 sm:px-8">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-24 h-64 bg-[radial-gradient(ellipse_at_center,color-mix(in_oklab,var(--color-glow)_16%,transparent),transparent_70%)]"
      />
      <header className="relative flex flex-wrap items-center justify-between gap-3">
        <h2 id="team-map" className="flex items-center gap-2 text-base font-semibold text-ink">
          <Waypoints aria-hidden size={16} strokeWidth={1.75} className="text-accent" />
          How the agents work together
        </h2>
        <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="h-px w-5 bg-line-strong" />
            CEO dispatches subtasks
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="w-5 border-t-2 border-dashed border-accent" />
            Departments ask each other
          </span>
        </p>
      </header>

      <div className="relative mt-6">
        <div className="mx-auto grid max-w-[15rem] gap-3">
          {supervisors.map((card) => (
            <MapNode key={card.name} card={card} selected={selected === card.name} onSelect={() => onSelect(card.name)} />
          ))}
        </div>

        {departments.length > 0 ? (
          <>
            {/* Connectors: a stem down from the CEO, then a rail spanning the department columns. */}
            <div aria-hidden className="mx-auto hidden h-8 w-px bg-line-strong sm:block" />
            <div aria-hidden className="hidden h-px bg-line-strong sm:block" style={{ marginInline: `${50 / columns}%` }} />
            <div className="mt-3 grid gap-3 sm:mt-0 sm:gap-6" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
              {departments.map((card, index) => (
                <div key={card.name} className="relative flex flex-col items-center">
                  <div aria-hidden className="hidden h-6 w-px shrink-0 bg-line-strong sm:block" />
                  {index < departments.length - 1 ? (
                    // The peer channel: a dashed link to the next department, through the gap.
                    <div
                      aria-hidden
                      className="absolute top-[calc(1.5rem+3.25rem)] -right-6 hidden w-6 border-t-2 border-dashed border-accent/70 sm:block"
                    />
                  ) : null}
                  <div className="w-full flex-1">
                    <MapNode card={card} selected={selected === card.name} onSelect={() => onSelect(card.name)} />
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}

// --- Agent detail --------------------------------------------------------------------------------

function SkillCard({ skill, index }: { skill: Skill; index: number }) {
  return (
    <li className="flex flex-col rounded-block border border-line bg-surface p-4 stagger" style={{ "--i": index } as CSSProperties}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-base font-semibold text-ink">{humanise(skill.name)}</p>
        <code className="mono-tag shrink-0">{skill.name}</code>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{skill.description}</p>
      {skill.example_questions.length > 0 ? (
        <ul className="mt-auto space-y-1.5 pt-3">
          {skill.example_questions.map((question) => (
            <li key={question}>
              <button
                type="button"
                onClick={() => askInChat(question)}
                className="group flex w-full items-start gap-2 rounded-lg bg-subtle px-2.5 py-2 text-left text-xs leading-snug text-ink-2 transition-colors hover:bg-accent-soft hover:text-accent-strong"
                title="Open the chat with this question"
              >
                <span className="min-w-0 flex-1">&ldquo;{question}&rdquo;</span>
                <span className="inline-flex shrink-0 items-center gap-0.5 font-medium text-faint transition-colors group-hover:text-accent-strong">
                  Ask
                  <ArrowUpRight aria-hidden size={12} strokeWidth={2} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function SidePanel({ card, peers }: { card: AgentCard; peers: AgentCard[] }) {
  return (
    <aside className="h-fit space-y-5 rounded-block bg-subtle/70 p-4">
      <div>
        <h3 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted">
          <Database aria-hidden size={13} strokeWidth={1.75} />
          Owns
        </h3>
        {card.owned_data.length === 0 ? (
          <p className="text-sm text-ink-2">No domain data. Reads agent cards and shared reference data only.</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {card.owned_data.map((item) => (
              <span key={item} className="mono-tag bg-surface!">
                {item}
              </span>
            ))}
          </div>
        )}
      </div>

      <div>
        <h3 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted">
          <Network aria-hidden size={13} strokeWidth={1.75} />
          {card.accepts_peer_requests ? "Can ask directly" : "Dispatches work to"}
        </h3>
        <ul className="space-y-2">
          {peers.map((peer) => (
            <li key={peer.name} className="flex items-center gap-2 text-sm">
              <AgentAvatar name={peer.name} size="sm" />
              <span className="font-medium text-ink">{agentLabel(peer.name)}</span>
              <span className="truncate text-xs text-muted">{peer.department}</span>
            </li>
          ))}
        </ul>
      </div>

      <p className="flex gap-2 border-t border-line pt-4 text-xs leading-relaxed text-muted">
        <Lock aria-hidden size={13} strokeWidth={1.75} className="mt-0.5 shrink-0" />
        {card.accepts_peer_requests
          ? "Its tools can only read the tables it owns. Anything else is requested from the owning agent."
          : "Never answers a domain question itself. It routes by these cards and combines the answers."}
      </p>
    </aside>
  );
}

function AgentDetail({ card, cards }: { card: AgentCard; cards: AgentCard[] }) {
  const style = agentStyle(card.name);
  const peers = cards.filter((other) => other.name !== card.name && other.accepts_peer_requests);
  return (
    <article className="card relative overflow-hidden animate-enter">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-40"
        style={{ background: `linear-gradient(to bottom, ${style.softColor}, transparent)` }}
      />
      <div className="relative grid gap-6 p-5 sm:p-7 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0">
          <header className="flex flex-wrap items-center gap-4">
            <span className="rounded-[16px] bg-surface p-1 shadow-raised ring-1 ring-line">
              <AgentAvatar name={card.name} size="lg" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-2xl font-semibold tracking-tight text-ink">{agentLabel(card.name)}</h2>
              <p className="text-sm text-muted">{card.department}</p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {card.accepts_peer_requests ? (
                <span className="chip bg-accent-soft text-accent-strong">
                  <Network aria-hidden size={11} strokeWidth={2} />
                  Answers peer requests
                </span>
              ) : (
                <span className="chip bg-surface text-ink-2 ring-1 ring-line">Supervisor</span>
              )}
              <span className="chip bg-surface text-ink-2 ring-1 ring-line">
                {card.skills.length} {card.skills.length === 1 ? "skill" : "skills"}
              </span>
            </div>
          </header>

          <p className="mt-5 max-w-[68ch] text-read text-ink-2">{card.description}</p>

          <h3 className="mt-7 mb-3 text-sm font-medium text-ink">Skills</h3>
          {card.skills.length === 0 ? (
            <p className="text-sm text-muted">No skills listed.</p>
          ) : (
            <ul className="grid gap-3 md:grid-cols-2">
              {card.skills.map((skill, index) => (
                <SkillCard key={skill.name} skill={skill} index={index} />
              ))}
            </ul>
          )}
        </div>
        <SidePanel card={card} peers={peers} />
      </div>
    </article>
  );
}

function AgentTabs({ cards, selected, onSelect }: { cards: AgentCard[]; selected: string; onSelect: (name: string) => void }) {
  return (
    <div role="tablist" aria-label="Agents" className="flex gap-1 overflow-x-auto rounded-block bg-subtle p-1">
      {cards.map((card) => {
        const active = card.name === selected;
        return (
          <button
            key={card.name}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onSelect(card.name)}
            className={`flex h-9 flex-1 items-center justify-center gap-2 rounded-[8px] px-3 text-sm whitespace-nowrap transition-colors ${
              active ? "bg-surface font-medium text-ink shadow-card" : "text-muted hover:text-ink"
            }`}
          >
            <AgentAvatar name={card.name} size="sm" />
            {agentLabel(card.name)}
          </button>
        );
      })}
    </div>
  );
}

export function AgentsPage() {
  const [agents, reload] = useResource(fetchAgents, "agents");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const cards = agents.data ?? [];
  const supervisors = cards.filter((card) => !card.accepts_peer_requests);
  const departments = cards.filter((card) => card.accepts_peer_requests);
  const ordered = [...supervisors, ...departments];
  const selected = ordered.find((card) => card.name === selectedName) ?? ordered[0];

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-8 sm:py-12">
        <PageHeader
          icon={Bot}
          title="Agents"
          description="Every agent registered with the backend. The CEO routes work using these cards, and each department reads only the data it owns."
        />

        {agents.status === "loading" && !agents.data ? (
          <div className="card p-6">
            <LoadingState label="Loading agents" lines={4} />
          </div>
        ) : null}
        {agents.status === "error" ? <ErrorState title="Could not load agents" detail={agents.error} onRetry={reload} /> : null}
        {agents.data && cards.length === 0 ? (
          <div className="card">
            <EmptyState title="No agents are registered" icon={<Bot size={20} strokeWidth={1.75} />}>
              Start the backend with the agent modules imported so they register themselves.
            </EmptyState>
          </div>
        ) : null}

        {selected ? (
          <>
            <Summary cards={cards} />
            <TeamMap supervisors={supervisors} departments={departments} selected={selected.name} onSelect={setSelectedName} />
            <div className="space-y-3">
              <AgentTabs cards={ordered} selected={selected.name} onSelect={setSelectedName} />
              <AgentDetail key={selected.name} card={selected} cards={ordered} />
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
