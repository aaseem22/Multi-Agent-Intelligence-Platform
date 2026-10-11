import { AlertTriangle, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

/** Three dots that breathe in sequence. Sits inline with text. */
export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span aria-hidden className={`inline-flex items-center gap-[3px] ${className}`}>
      {[0, 1, 2].map((i) => (
        <span key={i} className="size-1 animate-blink rounded-full bg-current" style={{ animationDelay: `${i * 0.18}s` }} />
      ))}
    </span>
  );
}

/** Skeleton lines shaped like the content that is loading. */
export function LoadingState({ label, lines = 3 }: { label: string; lines?: number }) {
  return (
    <div role="status" aria-label={label} className="space-y-3 py-2">
      <div className="skeleton h-5 w-2/5" />
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton h-3.5" style={{ width: `${92 - i * 14}%` }} />
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}

interface ErrorStateProps {
  title: string;
  detail: string;
  onRetry?: () => void;
}

export function ErrorState({ title, detail, onRetry }: ErrorStateProps) {
  return (
    <div role="alert" className="flex gap-3 rounded-block border border-danger/20 bg-danger-soft px-4 py-3.5">
      <AlertTriangle aria-hidden size={18} strokeWidth={1.75} className="mt-0.5 shrink-0 text-danger" />
      <div className="min-w-0">
        <p className="text-base font-medium text-danger">{title}</p>
        <p className="mt-0.5 max-w-[65ch] text-sm wrap-break-word text-ink-2">{detail}</p>
        {onRetry ? (
          <button type="button" onClick={onRetry} className="btn btn-secondary mt-3 h-8">
            <RotateCw aria-hidden size={14} strokeWidth={1.75} />
            Try again
          </button>
        ) : null}
      </div>
    </div>
  );
}

interface EmptyStateProps {
  title: string;
  icon?: ReactNode;
  children?: ReactNode;
}

export function EmptyState({ title, icon, children }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      {icon ? (
        <span className="mb-4 inline-flex size-11 items-center justify-center rounded-xl border border-line bg-surface text-muted shadow-card">
          {icon}
        </span>
      ) : null}
      <p className="text-base font-medium text-ink">{title}</p>
      {children ? <div className="mt-1 max-w-[40ch] text-sm text-muted">{children}</div> : null}
    </div>
  );
}
