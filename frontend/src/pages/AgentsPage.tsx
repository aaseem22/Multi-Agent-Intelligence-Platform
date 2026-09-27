import { backend } from "../api/backend";
import { AgentName } from "../components/AgentName";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { useResource } from "../hooks/useResource";
import { agentStroke } from "../lib/agents";
import type { AgentCard } from "../types/contracts";

const fetchAgents = (signal: AbortSignal) => backend.getAgents(signal);

function OwnedData({ items }: { items: string[] }) {
  if (items.length === 0) return <span className="text-graphite italic">no domain data</span>;
  return (
    <span className="font-mono text-2xs text-ink">
      {items.map((item, index) => (
        <span key={item}>
          {index > 0 ? <span className="text-pencil">, </span> : null}
          {item}
        </span>
      ))}
    </span>
  );
}

/** Directory summary: one line per agent, read across like a staff list. */
function Directory({ cards }: { cards: AgentCard[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">Registered agents</caption>
        <thead>
          <tr className="border-b border-rule-strong text-xs text-graphite">
            <th scope="col" className="py-1.5 pr-4 font-semibold">Agent</th>
            <th scope="col" className="py-1.5 pr-4 font-semibold">Department</th>
            <th scope="col" className="hidden py-1.5 pr-4 font-semibold sm:table-cell">Owns</th>
            <th scope="col" className="py-1.5 text-right font-semibold">Skills</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => (
            <tr key={card.name} className="border-b border-rule">
              <td className="py-2 pr-4">
                <AgentName name={card.name} />
              </td>
              <td className="py-2 pr-4 text-graphite">{card.department}</td>
              <td className="hidden py-2 pr-4 sm:table-cell">
                <OwnedData items={card.owned_data} />
              </td>
              <td className="py-2 text-right text-graphite">{card.skills.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One agent's spec sheet: identity in the left margin, what it does and knows on the right. */
function AgentSheet({ card }: { card: AgentCard }) {
  return (
    <article className="grid gap-x-10 gap-y-3 border-t border-rule-strong pt-6 md:grid-cols-[11rem_minmax(0,1fr)]">
      <header className="relative md:pl-4">
        <span aria-hidden className={`absolute top-1 bottom-1 left-0 hidden w-[3px] md:block ${agentStroke(card.name)}`} />
        <h2 className="text-xl">
          <AgentName name={card.name} />
        </h2>
        <p className="text-sm text-graphite italic">{card.department}</p>
        <p className="mt-2 text-xs text-graphite">
          {card.accepts_peer_requests ? "Answers peer requests" : "Does not take peer requests"}
        </p>
      </header>

      <div className="min-w-0 space-y-5">
        <p className="max-w-[62ch] text-read text-ink">{card.description}</p>

        <section aria-label={`${card.department} skills`}>
          <h3 className="border-b border-rule pb-1 text-xs font-semibold text-graphite">Skills</h3>
          {card.skills.length === 0 ? (
            <p className="mt-2 text-sm text-graphite italic">No skills listed.</p>
          ) : (
            <dl>
              {card.skills.map((skill) => (
                <div
                  key={skill.name}
                  className="grid gap-x-6 border-b border-rule py-2.5 last:border-b-0 sm:grid-cols-[13rem_minmax(0,1fr)]"
                >
                  <dt className="font-mono text-xs break-words text-ink">{skill.name}</dt>
                  <dd className="text-sm text-ink">
                    {skill.description}
                    {skill.example_questions.map((question) => (
                      <span key={question} className="mt-0.5 block text-graphite italic">
                        &ldquo;{question}&rdquo;
                      </span>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <p className="text-sm">
          <span className="mr-2 text-xs font-semibold text-graphite">Owns</span>
          <OwnedData items={card.owned_data} />
        </p>
      </div>
    </article>
  );
}

export function AgentsPage() {
  const [agents, reload] = useResource(fetchAgents, "agents");

  return (
    <div className="h-full overflow-y-auto px-4 py-8 sm:px-10 sm:py-12">
      <div className="max-w-5xl">
        <h1 className="text-2xl font-medium tracking-tight sm:text-[2.75rem] sm:leading-[1.1]">Agents</h1>
        <p className="mt-3 max-w-[60ch] text-base text-graphite">
          Every agent registered with the backend. The CEO routes subtasks using these descriptions, and each department
          can only read the data it owns.
        </p>

        <div className="mt-8">
          {agents.status === "loading" && !agents.data ? <LoadingState label="Loading agents" /> : null}
          {agents.status === "error" ? (
            <ErrorState title="Could not load agents" detail={agents.error} onRetry={reload} />
          ) : null}
          {agents.data && agents.data.length === 0 ? (
            <EmptyState title="No agents are registered">
              Start the backend with the agent modules imported so they register themselves.
            </EmptyState>
          ) : null}
          {agents.data && agents.data.length > 0 ? (
            <div className="space-y-12">
              <Directory cards={agents.data} />
              <div className="space-y-12">
                {agents.data.map((card) => (
                  <AgentSheet key={card.name} card={card} />
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
