import { AlertTriangle, Play, Search } from "lucide-react";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import type { Resource } from "../hooks/useResource";
import type { Dataset, RunConfig, Suite } from "../types/evals";
import { CALLS_PER_TRIAL, estimateMinutes, formatMinutes, humanise, REQUESTS_PER_MINUTE, SUITE_COPY } from "./lib";
import { SectionHead } from "./ui";

interface RunLauncherProps {
  datasets: Resource<Dataset[]>;
  busy: boolean;
  /** Resolves to an error message, or null when the run started. */
  onStart: (config: RunConfig) => Promise<string | null>;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <fieldset className="min-w-0 space-y-2">
      <legend className="text-sm font-medium text-ink">{label}</legend>
      {hint ? <p className="-mt-1 text-xs text-muted">{hint}</p> : null}
      {children}
    </fieldset>
  );
}

function Check({ checked, onChange, children, note }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; note?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-sm text-ink">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 size-4 shrink-0 accent-[var(--color-ink)]" />
      <span className="min-w-0">
        {children}
        {note ? <span className="block text-xs text-muted">{note}</span> : null}
      </span>
    </label>
  );
}

function Radio({ name, checked, onChange, children, note }: { name: string; checked: boolean; onChange: () => void; children: ReactNode; note?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-sm text-ink">
      <input type="radio" name={name} checked={checked} onChange={onChange} className="mt-0.5 size-4 shrink-0 accent-[var(--color-ink)]" />
      <span className="min-w-0">
        {children}
        {note ? <span className="block text-xs text-muted">{note}</span> : null}
      </span>
    </label>
  );
}

export function RunLauncher({ datasets, busy, onStart }: RunLauncherProps) {
  const list = useMemo(() => datasets.data ?? [], [datasets.data]);
  const [datasetName, setDatasetName] = useState<string | null>(null);
  const [suites, setSuites] = useState<Suite[]>(["capability", "regression"]);
  const [pick, setPick] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");
  const [trials, setTrials] = useState(1);
  const [judge, setJudge] = useState(true);
  const [recovery, setRecovery] = useState<RunConfig["self_eval_recovery"]>("retry");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "ok"; text: string } | null>(null);

  const dataset = list.find((d) => d.name === datasetName) ?? list.find((d) => d.name === "golden") ?? list[0];
  const inSuites = useMemo(() => (dataset?.tasks ?? []).filter((t) => suites.includes(t.suite)), [dataset, suites]);
  const chosen = pick ? inSuites.filter((t) => picked.has(t.id)) : inSuites;
  const minutes = estimateMinutes(chosen.length, trials);
  const filtered = query ? inSuites.filter((t) => `${t.id} ${t.question} ${t.category}`.toLowerCase().includes(query.toLowerCase())) : inSuites;

  const toggleSuite = (suite: Suite, on: boolean) => setSuites((current) => (on ? [...new Set([...current, suite])] : current.filter((s) => s !== suite)));
  const togglePicked = (id: string, on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const disabled = busy || submitting || !dataset || chosen.length === 0 || suites.length === 0;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (disabled || !dataset) return;
    setSubmitting(true);
    setMessage(null);
    const error = await onStart({
      dataset: dataset.name,
      suites,
      task_ids: pick ? chosen.map((t) => t.id) : [],
      trials,
      judge_enabled: judge,
      self_eval_recovery: recovery,
    });
    setSubmitting(false);
    setMessage(error ? { tone: "error", text: error } : { tone: "ok", text: "Run queued. Progress appears above." });
  };

  return (
    <section aria-labelledby="launcher" className="card overflow-hidden">
      <form onSubmit={submit}>
        <div className="border-b border-line px-5 py-4">
          <SectionHead id="launcher" title="Start a run">
            Each run seeds a fresh fixture database and replays every chosen task as a real chat request, then grades the transcript. One run at a time.
          </SectionHead>
        </div>
        <div className="grid gap-x-10 gap-y-6 p-5 lg:grid-cols-[minmax(0,1fr)_19rem]">
          <div className="grid gap-x-8 gap-y-6 sm:grid-cols-2">
            <Field label="Dataset">
              {datasets.status === "error" && !datasets.data ? (
                <p className="text-sm text-danger">Could not load datasets: {datasets.error}</p>
              ) : (
                <select
                  value={dataset?.name ?? ""}
                  onChange={(e) => {
                    setDatasetName(e.target.value);
                    setPicked(new Set());
                  }}
                  className="h-9 w-full rounded-block border border-line bg-surface px-2.5 text-sm text-ink shadow-card"
                >
                  {list.map((d) => (
                    <option key={d.name} value={d.name}>
                      {d.name} v{d.version} ({d.tasks.length} tasks)
                    </option>
                  ))}
                </select>
              )}
              {dataset ? <p className="text-xs text-muted">{dataset.description}</p> : null}
            </Field>

            <Field label="Suites">
              {(["regression", "capability"] as const).map((suite) => (
                <Check key={suite} checked={suites.includes(suite)} onChange={(on) => toggleSuite(suite, on)} note={SUITE_COPY[suite].line}>
                  {SUITE_COPY[suite].label}
                </Check>
              ))}
            </Field>

            <Field label="Trials per task" hint="pass^k needs 2 or more; 3 is a good default for consistency.">
              <div role="radiogroup" aria-label="Trials per task" className="flex gap-1 rounded-block bg-subtle p-1">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    role="radio"
                    aria-checked={trials === n}
                    onClick={() => setTrials(n)}
                    className={`h-7 flex-1 rounded-[7px] text-sm tabular-nums transition-colors ${trials === n ? "bg-surface font-medium text-ink shadow-card" : "text-muted hover:text-ink"}`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </Field>

            <Field label="Grading and recovery">
              <Check checked={judge} onChange={setJudge} note="Off skips model graders; only code graders run.">
                Use the judge model
              </Check>
              <Radio name="recovery" checked={recovery === "retry"} onChange={() => setRecovery("retry")} note="Agents re-run once with the reviewer's feedback, as in live chat.">
                Self-evaluation retries
              </Radio>
              <Radio name="recovery" checked={recovery === "observe"} onChange={() => setRecovery("observe")} note="Reviews are recorded but never trigger a retry.">
                Observe only
              </Radio>
            </Field>

            <div className="sm:col-span-2">
              <Field label="Tasks">
                <div className="flex flex-wrap gap-x-6 gap-y-2">
                  <Radio name="subset" checked={!pick} onChange={() => setPick(false)}>
                    All {inSuites.length} tasks in the chosen suites
                  </Radio>
                  <Radio name="subset" checked={pick} onChange={() => setPick(true)}>
                    Pick tasks{pick ? ` (${chosen.length} picked)` : ""}
                  </Radio>
                </div>
                {pick ? (
                  <div className="mt-2 rounded-block border border-line">
                    <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
                      <Search aria-hidden size={14} strokeWidth={1.75} className="text-faint" />
                      <input
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Filter by id, question or category"
                        aria-label="Filter tasks"
                        className="h-7 min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-faint focus:outline-none"
                      />
                      <button type="button" className="btn btn-ghost h-7 px-2 text-xs" onClick={() => setPicked(new Set(filtered.map((t) => t.id)))}>
                        Select shown
                      </button>
                      <button type="button" className="btn btn-ghost h-7 px-2 text-xs" onClick={() => setPicked(new Set())}>
                        Clear
                      </button>
                    </div>
                    <ul className="max-h-64 overflow-y-auto py-1">
                      {filtered.map((task) => (
                        <li key={task.id}>
                          <label className="flex cursor-pointer items-start gap-2.5 px-3 py-1.5 text-sm hover:bg-subtle/70">
                            <input
                              type="checkbox"
                              checked={picked.has(task.id)}
                              onChange={(e) => togglePicked(task.id, e.target.checked)}
                              className="mt-0.5 size-4 shrink-0 accent-[var(--color-ink)]"
                            />
                            <span className="w-16 shrink-0 font-mono text-xs leading-5 text-muted">{task.id}</span>
                            <span className="min-w-0 flex-1 text-ink-2">{task.question}</span>
                            <span className="hidden shrink-0 text-xs leading-5 text-faint sm:inline">{humanise(task.category)}</span>
                          </label>
                        </li>
                      ))}
                      {filtered.length === 0 ? <li className="px-3 py-2 text-sm text-muted">No task matches.</li> : null}
                    </ul>
                  </div>
                ) : null}
              </Field>
            </div>
          </div>

          <aside className="flex h-fit flex-col gap-4 rounded-block bg-subtle p-4">
            <div>
              <p className="text-xs text-muted">Estimated duration</p>
              <p className="mt-1 text-2xl leading-none font-semibold tracking-tight text-ink tabular-nums">{chosen.length ? `~${formatMinutes(minutes)}` : "-"}</p>
              <p className="mt-1.5 text-sm text-ink-2">
                {chosen.length} {chosen.length === 1 ? "task" : "tasks"} x {trials} {trials === 1 ? "trial" : "trials"} = {chosen.length * trials} chat requests
              </p>
            </div>
            <p className="flex gap-2 text-xs leading-relaxed text-warn">
              <AlertTriangle aria-hidden size={14} strokeWidth={1.75} className="mt-0.5 shrink-0" />
              <span>
                The Gemini free tier allows about {REQUESTS_PER_MINUTE} requests a minute and each task makes about {CALLS_PER_TRIAL} calls, so 25 tasks with one trial take about 30 minutes. Chat
                requests made while a run is going will be slow.
              </span>
            </p>
            <button type="submit" disabled={disabled} className="btn btn-primary w-full">
              <Play aria-hidden size={14} strokeWidth={2} />
              {submitting ? "Starting" : "Start run"}
            </button>
            {busy ? <p className="text-xs text-muted">A run is already in progress. Wait for it to finish or cancel it first.</p> : null}
            {message ? (
              <p role={message.tone === "error" ? "alert" : "status"} className={`text-sm ${message.tone === "error" ? "text-danger" : "text-ok"}`}>
                {message.text}
              </p>
            ) : null}
          </aside>
        </div>
      </form>
    </section>
  );
}
