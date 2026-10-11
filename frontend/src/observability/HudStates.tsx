import { Activity, AlertTriangle, CloudOff, PlugZap, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

function StateFrame({ icon, tone = "neutral", children }: { icon: ReactNode; tone?: "neutral" | "danger"; children: ReactNode }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4 py-10">
      <div className="card flex w-full max-w-xl flex-col items-start gap-5 p-8 animate-enter">
        <span
          className={`inline-flex size-11 items-center justify-center rounded-xl ${
            tone === "danger" ? "bg-danger-soft text-danger" : "bg-accent-soft text-accent"
          }`}
        >
          {icon}
        </span>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}

/** Skeleton shaped like the dashboard, shown on first load. */
export function BootState() {
  return (
    <div role="status" aria-label="Loading traces from Langfuse" className="obs-grid">
      <div className="obs-main">
        <div className="obs-panel obs-area-reactor space-y-4">
          <div className="skeleton h-4 w-24" />
          <div className="skeleton mx-auto aspect-square w-3/4 rounded-full!" />
          <div className="skeleton h-3 w-full" />
          <div className="skeleton h-3 w-4/5" />
        </div>
        <div className="obs-panel obs-area-constellation space-y-4">
          <div className="skeleton h-4 w-36" />
          <div className="skeleton h-72 w-full" />
        </div>
        <div className="obs-panel obs-area-telemetry space-y-4">
          <div className="skeleton h-4 w-28" />
          <div className="skeleton h-28 w-full" />
        </div>
      </div>
      <div className="obs-panel obs-area-feed space-y-3">
        <div className="skeleton h-4 w-24" />
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="skeleton h-16 w-full" />
        ))}
      </div>
    </div>
  );
}

const ENV_VARS = [
  ["LANGFUSE_PUBLIC_KEY", "pk-lf-..."],
  ["LANGFUSE_SECRET_KEY", "sk-lf-..."],
  ["LANGFUSE_HOST", "https://cloud.langfuse.com"],
];

export function DisabledState({ reason, onRetry }: { reason: string | null; onRetry: () => void }) {
  return (
    <StateFrame icon={<PlugZap size={20} strokeWidth={1.75} />}>
      <h2 className="text-xl font-semibold tracking-tight">Tracing is off</h2>
      <p className="mt-2 max-w-[56ch] text-read text-muted">
        The dashboard reads traces from Langfuse, and the backend has no working Langfuse connection.
      </p>
      {reason ? <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 font-mono text-xs text-warn">{reason}</p> : null}
      <p className="mt-5 text-sm text-ink-2">Add these to the repository's .env file:</p>
      <pre className="mt-2 overflow-x-auto rounded-block bg-subtle px-4 py-3 font-mono text-xs leading-6">
        {ENV_VARS.map(([key, example]) => (
          <span key={key} className="block">
            <span className="text-accent">{key}</span>
            <span className="text-faint">=</span>
            <span className="text-ink-2">{example}</span>
          </span>
        ))}
      </pre>
      <p className="mt-3 text-sm text-muted">Restart the backend, ask a question in the console, then check again.</p>
      <div className="mt-5 flex flex-wrap gap-2">
        <button type="button" onClick={onRetry} className="btn btn-primary">
          <RefreshCw size={14} strokeWidth={1.75} aria-hidden />
          Check again
        </button>
        <a href="#/chat" className="btn btn-secondary">
          Open the console
        </a>
      </div>
    </StateFrame>
  );
}

/** Langfuse is configured but did not answer (network, rate limit, server error): retry, not reconfigure. */
export function UnreachableState({ reason, onRetry }: { reason: string | null; onRetry: () => void }) {
  return (
    <StateFrame icon={<CloudOff size={20} strokeWidth={1.75} />}>
      <h2 className="text-xl font-semibold tracking-tight">Langfuse is not answering right now</h2>
      <p className="mt-2 max-w-[56ch] text-read text-muted">
        Tracing is set up correctly, but Langfuse did not respond in time. This is usually a short network blip or
        its free-tier rate limit. The dashboard retries on its own every 20 seconds.
      </p>
      {reason ? <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 font-mono text-xs text-warn">{reason}</p> : null}
      <div className="mt-5 flex flex-wrap gap-2">
        <button type="button" onClick={onRetry} className="btn btn-primary">
          <RefreshCw size={14} strokeWidth={1.75} aria-hidden />
          Try again
        </button>
        <a href="#/chat" className="btn btn-secondary">
          Open the console
        </a>
      </div>
    </StateFrame>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <StateFrame tone="danger" icon={<AlertTriangle size={20} strokeWidth={1.75} />}>
      <div role="alert">
        <h2 className="text-xl font-semibold tracking-tight text-danger">Could not reach the backend</h2>
        <p className="mt-2 max-w-[56ch] text-read text-muted">
          The dashboard could not load its data. Check that the backend is running.
        </p>
        <p className="mt-3 font-mono text-xs break-words text-faint">{message}</p>
        <button type="button" onClick={onRetry} className="btn btn-primary mt-5">
          <RefreshCw size={14} strokeWidth={1.75} aria-hidden />
          Try again
        </button>
      </div>
    </StateFrame>
  );
}

export function EmptyState({ days, onWiden }: { days: number; onWiden: (() => void) | null }) {
  return (
    <StateFrame icon={<Activity size={20} strokeWidth={1.75} />}>
      <h2 className="text-xl font-semibold tracking-tight">No traces in the last {days === 1 ? "24 hours" : `${days} days`}</h2>
      <p className="mt-2 max-w-[56ch] text-read text-muted">
        Langfuse is connected. Every question asked in the console becomes one trace here, with its agent runs, tool
        calls and peer calls.
      </p>
      <div className="mt-5 flex flex-wrap gap-2">
        <a href="#/chat" className="btn btn-primary">
          Ask a question
        </a>
        {onWiden ? (
          <button type="button" onClick={onWiden} className="btn btn-secondary">
            Look back 30 days
          </button>
        ) : null}
      </div>
    </StateFrame>
  );
}
