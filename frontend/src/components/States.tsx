import { AlertTriangle, LoaderCircle, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

export function Spinner({ className = "size-4" }: { className?: string }) {
  return <LoaderCircle aria-hidden className={`animate-spin text-faint ${className}`} />;
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div role="status" className="flex items-center gap-2 px-4 py-6 text-sm text-muted">
      <Spinner />
      {label}
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
    <div role="alert" className="rounded-lg border border-fail/30 bg-fail/5 px-4 py-3 text-sm">
      <div className="flex items-start gap-2">
        <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-fail" />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-fail">{title}</p>
          <p className="mt-0.5 break-words text-muted">{detail}</p>
        </div>
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-ink hover:bg-paper"
          >
            <RotateCw aria-hidden className="size-3" />
            Try again
          </button>
        ) : null}
      </div>
    </div>
  );
}

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
}

export function EmptyState({ icon, title, children }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <div className="mb-3 text-faint">{icon}</div>
      <p className="font-medium text-ink">{title}</p>
      {children ? <div className="mt-1 max-w-sm text-sm text-muted">{children}</div> : null}
    </div>
  );
}
