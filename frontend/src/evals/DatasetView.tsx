import { ChevronRight, Database } from "lucide-react";
import { useState, type ReactNode } from "react";
import { AgentName } from "../components/AgentName";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import type { Dataset, EvalTask, RequiredFact, Suite } from "../types/evals";
import { humanise, kindOf, SUITE_COPY, useEvals } from "./lib";
import { SectionHead } from "./ui";

const NO_KINDS = new Map();
const PEER_COPY = { required: "At least one peer request is required", forbidden: "No peer requests allowed", any: "Peer requests optional" } as const;

function Names({ names, empty = "-" }: { names: string[]; empty?: string }) {
  if (names.length === 0) return <span className="text-muted">{empty}</span>;
  return (
    <span className="inline-flex flex-wrap gap-x-2">
      {names.map((n, i) => (
        <span key={n}>
          <AgentName name={n} />
          {i < names.length - 1 ? "," : ""}
        </span>
      ))}
    </span>
  );
}

function Facts({ facts }: { facts: RequiredFact[] }) {
  return (
    <ul className="space-y-1.5">
      {facts.map((fact) => (
        <li key={fact.description} className="text-sm">
          <span className="text-ink">{fact.description}</span>
          <span className="mt-0.5 flex flex-wrap gap-1">
            {fact.any_of.map((alt) => (
              <code key={alt} className="rounded-md bg-subtle px-1.5 py-0.5 font-mono text-2xs text-ink-2">
                {alt}
              </code>
            ))}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="grid gap-x-4 gap-y-0.5 sm:grid-cols-[11rem_minmax(0,1fr)]">
      <dt className="text-xs text-muted sm:pt-0.5">{term}</dt>
      <dd className="min-w-0 text-sm text-ink-2">{children}</dd>
    </div>
  );
}

function TaskItem({ task }: { task: EvalTask }) {
  const e = task.expected;
  return (
    <li className="border-t border-line first:border-t-0">
      <details className="group/task">
        <summary className="grid cursor-pointer grid-cols-[1rem_4.5rem_minmax(0,1fr)] items-start gap-x-3 px-5 py-3 transition-colors hover:bg-subtle/60">
          <ChevronRight aria-hidden size={14} strokeWidth={1.75} className="mt-0.5 text-faint transition-transform group-open/task:rotate-90" />
          <span className="font-mono text-xs leading-5 text-muted">{task.id}</span>
          <span className="text-sm text-ink">{task.question}</span>
        </summary>
        <dl className="space-y-3 px-5 pt-1 pb-5 sm:pl-[6.5rem]">
          {task.notes ? (
            <Row term="Why it exists">
              <span className="text-ink">{task.notes}</span>
            </Row>
          ) : null}
          {e.clarification ? (
            <Row term="Expected behaviour">The CEO asks a clarifying question and dispatches no agents.</Row>
          ) : (
            <>
              <Row term="Agents required">
                <Names names={e.agents_required} />
                {e.max_agents !== null ? <span className="text-muted">, at most {e.max_agents}</span> : null}
              </Row>
              {e.agents_forbidden.length > 0 ? (
                <Row term="Agents forbidden">
                  <Names names={e.agents_forbidden} />
                </Row>
              ) : null}
              <Row term="Peer messages">{PEER_COPY[e.peer_messages]}</Row>
            </>
          )}
          {e.must_report_unanswered ? <Row term="Honesty">Must say plainly what could not be answered.</Row> : null}
          {e.required_facts.length > 0 ? (
            <Row term="Required facts">
              <Facts facts={e.required_facts} />
            </Row>
          ) : null}
          {e.forbidden_facts.length > 0 ? (
            <Row term="Must not appear">
              <Facts facts={e.forbidden_facts} />
            </Row>
          ) : null}
          {e.reference_answer ? (
            <Row term="Reference answer">
              <span className="block border-l-2 border-line-strong pl-2.5 text-ink">{e.reference_answer}</span>
            </Row>
          ) : null}
          <Row term="Graders">
            <span className="flex flex-wrap gap-x-3 gap-y-1">
              {task.graders.map((g) => (
                <span key={g}>
                  <span className="font-mono text-xs text-ink">{g}</span> <span className="text-2xs text-faint">{kindOf(g, NO_KINDS)}</span>
                </span>
              ))}
            </span>
          </Row>
          {task.tags.length > 0 ? <Row term="Tags">{task.tags.join(", ")}</Row> : null}
        </dl>
      </details>
    </li>
  );
}

function DatasetBody({ dataset, suite }: { dataset: Dataset; suite: Suite | "all" }) {
  const tasks = dataset.tasks.filter((t) => suite === "all" || t.suite === suite);
  const groups = new Map<string, EvalTask[]>();
  for (const task of tasks.toSorted((a, b) => a.suite.localeCompare(b.suite) || a.category.localeCompare(b.category) || a.id.localeCompare(b.id))) {
    const key = `${task.suite}|${task.category}`;
    groups.set(key, [...(groups.get(key) ?? []), task]);
  }
  return (
    <div>
      {[...groups.entries()].map(([key, list]) => {
        const [s, category] = key.split("|") as [Suite, string];
        return (
          <section key={key} aria-label={`${SUITE_COPY[s].label}, ${humanise(category)}`}>
            <h3 className="border-t border-line bg-subtle px-5 py-2 text-sm font-semibold text-ink">
              {humanise(category)}{" "}
              <span className="font-normal text-muted">
                {SUITE_COPY[s].label.toLowerCase()} suite, {list.length} {list.length === 1 ? "task" : "tasks"}
              </span>
            </h3>
            <ul>
              {list.map((task) => (
                <TaskItem key={task.id} task={task} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export function DatasetView() {
  const [datasets, reload] = useEvals((client, signal) => client.getDatasets(signal), "evals-datasets");
  const [name, setName] = useState<string | null>(null);
  const [suite, setSuite] = useState<Suite | "all">("all");

  if (datasets.status === "loading" && !datasets.data) {
    return (
      <div className="card p-6">
        <LoadingState label="Loading datasets" lines={6} />
      </div>
    );
  }
  if (datasets.status === "error" && !datasets.data) return <ErrorState title="Could not load datasets" detail={datasets.error} onRetry={reload} />;
  const list = datasets.data ?? [];
  if (list.length === 0) {
    return (
      <div className="card">
        <EmptyState title="No datasets found" icon={<Database size={20} strokeWidth={1.75} />}>
          Datasets are JSON files in <code className="font-mono text-xs">backend/evals/datasets/</code>.
        </EmptyState>
      </div>
    );
  }
  const dataset = list.find((d) => d.name === name) ?? list[0];
  const counts = { capability: dataset.tasks.filter((t) => t.suite === "capability").length, regression: dataset.tasks.filter((t) => t.suite === "regression").length };
  const select = "h-8 rounded-block border border-line bg-surface px-2 text-sm text-ink shadow-card";

  return (
    <section className="card overflow-hidden" aria-labelledby="dataset">
      <div className="space-y-3 px-5 py-4">
        <SectionHead
          id="dataset"
          title={`${dataset.name} v${dataset.version}`}
          actions={
            <div className="flex flex-wrap gap-3">
              {list.length > 1 ? (
                <label className="flex items-center gap-2 text-sm text-muted">
                  Dataset
                  <select className={select} value={dataset.name} onChange={(e) => setName(e.target.value)}>
                    {list.map((d) => (
                      <option key={d.name} value={d.name}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="flex items-center gap-2 text-sm text-muted">
                Suite
                <select className={select} value={suite} onChange={(e) => setSuite(e.target.value as Suite | "all")}>
                  <option value="all">All ({dataset.tasks.length})</option>
                  <option value="regression">Regression ({counts.regression})</option>
                  <option value="capability">Capability ({counts.capability})</option>
                </select>
              </label>
            </div>
          }
        >
          {dataset.description} Each task is a question with clear success criteria; graders check the outcome, not the exact path the agents took.
        </SectionHead>
      </div>
      <DatasetBody dataset={dataset} suite={suite} />
    </section>
  );
}
