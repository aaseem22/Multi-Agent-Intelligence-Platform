import { Database, Inbox, MessageSquareShare, Users } from "lucide-react";
import { backend } from "../api/backend";
import { AgentBadge } from "../components/AgentBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { useResource } from "../hooks/useResource";
import { agentTone } from "../lib/agents";
import type { AgentCard } from "../types/contracts";

const fetchAgents = (signal: AbortSignal) => backend.getAgents(signal);

function AgentCardView({ card }: { card: AgentCard }) {
  const tone = agentTone(card.name);
  return (
    <article className="flex flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <div aria-hidden className={`h-1 ${tone.dot}`} />
      <header className="px-5 pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <AgentBadge name={card.name} size="md" />
          <span className="text-sm text-muted">{card.department}</span>
        </div>
        <p className="mt-2 max-w-[70ch] text-[15px] leading-relaxed text-ink">{card.description}</p>
      </header>

      <section aria-label="Skills" className="mt-4 px-5">
        <h3 className="text-sm font-semibold text-ink">Skills</h3>
        {card.skills.length === 0 ? (
          <p className="mt-1 text-sm text-faint">No skills listed.</p>
        ) : (
          <ul className="mt-1.5 divide-y divide-line">
            {card.skills.map((skill) => (
              <li key={skill.name} className="py-2">
                <p className="font-mono text-[13px] text-ink">{skill.name}</p>
                <p className="text-sm text-muted">{skill.description}</p>
                {skill.example_questions.length > 0 ? (
                  <ul className="mt-1 space-y-0.5">
                    {skill.example_questions.map((question) => (
                      <li key={question} className="text-sm text-ink/80 italic">
                        "{question}"
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="mt-auto flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line px-5 py-3 text-sm">
        <div className="flex flex-wrap items-center gap-1.5">
          <Database aria-hidden className="size-4 text-faint" />
          <span className="text-muted">Owns</span>
          {card.owned_data.length === 0 ? (
            <span className="text-faint">no domain data</span>
          ) : (
            card.owned_data.map((item) => (
              <code key={item} className="rounded bg-paper px-1.5 py-0.5 font-mono text-xs text-ink">
                {item}
              </code>
            ))
          )}
        </div>
        <span className="inline-flex items-center gap-1.5 text-muted">
          <MessageSquareShare aria-hidden className="size-4 text-faint" />
          {card.accepts_peer_requests ? "Answers peer requests" : "Does not take peer requests"}
        </span>
      </footer>
    </article>
  );
}

export function AgentsPage() {
  const [agents, reload] = useResource(fetchAgents, "agents");

  return (
    <div className="h-full overflow-y-auto px-4 py-8 sm:px-8">
      <div className="mx-auto max-w-5xl">
        <header className="mb-6 flex items-center gap-2">
          <Users aria-hidden className="size-5 text-chrome" />
          <h1 className="text-2xl font-semibold tracking-tight">Agents</h1>
        </header>
        <p className="-mt-4 mb-6 max-w-[65ch] text-muted">
          Every agent registered with the backend. The CEO routes subtasks using these descriptions, and each department
          can only read the data it owns.
        </p>

        {agents.status === "loading" && !agents.data ? <LoadingState label="Loading agents" /> : null}
        {agents.status === "error" ? (
          <ErrorState title="Could not load agents" detail={agents.error} onRetry={reload} />
        ) : null}
        {agents.data && agents.data.length === 0 ? (
          <EmptyState icon={<Inbox className="size-8" />} title="No agents are registered">
            Start the backend with the agent modules imported so they register themselves.
          </EmptyState>
        ) : null}
        {agents.data && agents.data.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2">
            {agents.data.map((card) => (
              <AgentCardView key={card.name} card={card} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
