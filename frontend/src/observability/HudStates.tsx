import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

function DimReactor({ scanning = false, alert = false }: { scanning?: boolean; alert?: boolean }) {
  const accent = alert ? "var(--obs-alert)" : "var(--obs-ice)";
  return (
    <svg width="220" height="220" viewBox="0 0 220 220" aria-hidden className="shrink-0">
      <defs>
        <radialGradient id="obs-dim-core">
          <stop offset="0%" stopColor={alert ? "rgba(255,93,82,0.2)" : "rgba(127,220,255,0.2)"} />
          <stop offset="100%" stopColor="rgba(0,0,0,0)" />
        </radialGradient>
      </defs>
      {Array.from({ length: 72 }, (_, i) => {
        const a = (i / 72) * Math.PI * 2;
        const major = i % 6 === 0;
        const r1 = major ? 94 : 99;
        return (
          <line
            key={i}
            x1={(110 + Math.cos(a) * r1).toFixed(1)}
            y1={(110 + Math.sin(a) * r1).toFixed(1)}
            x2={(110 + Math.cos(a) * 103).toFixed(1)}
            y2={(110 + Math.sin(a) * 103).toFixed(1)}
            stroke={major ? "var(--obs-ice-dim)" : "var(--obs-line-strong)"}
          />
        );
      })}
      {[84, 70, 56].map((r, i) => (
        <circle
          key={r}
          cx="110"
          cy="110"
          r={r}
          fill="none"
          stroke="var(--obs-line)"
          strokeWidth="6"
          className={scanning ? "obs-breathe" : undefined}
          style={scanning ? { animationDelay: `${i * 0.3}s` } : undefined}
        />
      ))}
      {scanning ? (
        <g className="obs-sweep-fast" style={{ animationDuration: "1.8s" }}>
          <circle cx="110" cy="110" r="84" fill="none" stroke="none" />
          <path d="M110 26 A84 84 0 0 1 182.7 68" fill="none" stroke={accent} strokeWidth="6" strokeLinecap="round" style={{ filter: "drop-shadow(0 0 6px rgba(127,220,255,0.7))" }} />
        </g>
      ) : null}
      <circle cx="110" cy="110" r="40" fill="url(#obs-dim-core)" className={scanning ? "obs-breathe" : undefined} />
      <circle cx="110" cy="110" r="40" fill="none" stroke={alert ? "var(--obs-alert)" : "var(--obs-line-strong)"} strokeDasharray="2 4" />
    </svg>
  );
}

function StateFrame({ children, reactor }: { children: ReactNode; reactor: ReactNode }) {
  return (
    <div className="flex min-h-[calc(100vh-72px)] items-center justify-center px-4 py-10">
      <div className="obs-panel flex w-full max-w-3xl flex-col items-center gap-8 px-6 py-10 md:flex-row md:px-10">
        <span aria-hidden className="obs-corner obs-corner--tl" />
        <span aria-hidden className="obs-corner obs-corner--tr" />
        <span aria-hidden className="obs-corner obs-corner--bl" />
        <span aria-hidden className="obs-corner obs-corner--br" />
        {reactor}
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}

const BOOT_LINES = ["Linking to the backend", "Querying Langfuse traces", "Aggregating spans and scores", "Plotting agent traffic"];

export function BootState() {
  return (
    <StateFrame reactor={<DimReactor scanning />}>
      <div role="status" aria-live="polite">
        <p className="obs-title">Bringing the instruments online</p>
        <ol className="obs-mono mt-5 space-y-2 text-sm">
          {BOOT_LINES.map((line, i) => (
            <li key={line} className="obs-boot-line flex items-center gap-3 obs-t2" style={{ animationDelay: `${0.15 + i * 0.35}s` }}>
              <span aria-hidden className="obs-ice">›</span>
              {line}
            </li>
          ))}
        </ol>
      </div>
    </StateFrame>
  );
}

const ENV_VARS = [
  ["LANGFUSE_PUBLIC_KEY", "pk-lf-…"],
  ["LANGFUSE_SECRET_KEY", "sk-lf-…"],
  ["LANGFUSE_HOST", "https://cloud.langfuse.com"],
];

export function DisabledState({ reason, onRetry }: { reason: string | null; onRetry: () => void }) {
  return (
    <StateFrame reactor={<DimReactor />}>
      <h2 className="obs-title">Tracing is off</h2>
      <p className="obs-t2 mt-3 max-w-[56ch] text-base leading-relaxed">
        The dashboard reads traces from Langfuse, and the backend has no working Langfuse connection.
      </p>
      {reason ? <p className="obs-mono obs-amber mt-3 max-w-[64ch] text-xs leading-relaxed">{reason}</p> : null}
      <p className="obs-cond obs-t2 mt-5 text-sm">Add these to the repository's .env file:</p>
      <pre className="obs-mono mt-2 overflow-x-auto border border-(--obs-line) bg-(--obs-void) px-4 py-3 text-xs leading-6">
        {ENV_VARS.map(([key, example]) => (
          <span key={key} className="block">
            <span className="obs-ice">{key}</span>
            <span className="obs-t3">=</span>
            <span className="obs-t2">{example}</span>
          </span>
        ))}
      </pre>
      <p className="obs-t2 mt-3 text-sm">Restart the backend, ask a question in the console, then check again.</p>
      <div className="mt-5 flex flex-wrap gap-3">
        <button type="button" onClick={onRetry} className="obs-button obs-button--primary">
          <RefreshCw size={14} aria-hidden />
          Check again
        </button>
        <a href="#/chat" className="obs-button">
          Open the console
        </a>
      </div>
    </StateFrame>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <StateFrame reactor={<DimReactor alert />}>
      <div role="alert">
        <h2 className="obs-title obs-alert">No signal from the backend</h2>
        <p className="obs-t2 mt-3 max-w-[56ch] text-base leading-relaxed">
          The dashboard could not load its data. Check that the backend is running on port 8000.
        </p>
        <p className="obs-mono obs-t3 mt-3 text-xs break-words">{message}</p>
        <button type="button" onClick={onRetry} className="obs-button obs-button--primary mt-5">
          <RefreshCw size={14} aria-hidden />
          Try again
        </button>
      </div>
    </StateFrame>
  );
}

export function EmptyState({ days, onWiden }: { days: number; onWiden: (() => void) | null }) {
  return (
    <StateFrame reactor={<DimReactor />}>
      <h2 className="obs-title">No traces in the last {days === 1 ? "24 hours" : `${days} days`}</h2>
      <p className="obs-t2 mt-3 max-w-[56ch] text-base leading-relaxed">
        Langfuse is connected. Every question asked in the console becomes one trace here, with its agent runs, tool
        calls and peer calls.
      </p>
      <div className="mt-5 flex flex-wrap gap-3">
        <a href="#/chat" className="obs-button obs-button--primary">
          Ask a question
        </a>
        {onWiden ? (
          <button type="button" onClick={onWiden} className="obs-button">
            Look back 30 days
          </button>
        ) : null}
      </div>
    </StateFrame>
  );
}
