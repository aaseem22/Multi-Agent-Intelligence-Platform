import type { ReactNode } from "react";

/** A three-dot "still writing" mark. Quieter than a spinner and at home in running text. */
export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span aria-hidden className={`inline-flex items-center gap-[3px] ${className}`}>
      <span className="size-[4px] animate-breathe rounded-full bg-current" />
      <span className="size-[4px] animate-breathe rounded-full bg-current [animation-delay:0.2s]" />
      <span className="size-[4px] animate-breathe rounded-full bg-current [animation-delay:0.4s]" />
    </span>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <p role="status" className="flex items-baseline gap-2.5 py-6 text-sm text-graphite italic">
      {label}
      <Spinner className="text-pencil" />
    </p>
  );
}

interface ErrorStateProps {
  title: string;
  detail: string;
  onRetry?: () => void;
}

/** A failure reads as a marginal note in red: a rule on the left, the reason, and a way forward. */
export function ErrorState({ title, detail, onRetry }: ErrorStateProps) {
  return (
    <div role="alert" className="border-l-2 border-refuse py-1 pl-4">
      <p className="font-semibold text-refuse">{title}</p>
      <p className="mt-1 max-w-[65ch] text-sm break-words text-graphite">{detail}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="link mt-2 text-sm font-semibold text-ink">
          Try again
        </button>
      ) : null}
    </div>
  );
}

interface EmptyStateProps {
  title: string;
  children?: ReactNode;
}

export function EmptyState({ title, children }: EmptyStateProps) {
  return (
    <div className="py-8">
      <p className="text-base font-semibold text-ink">{title}</p>
      {children ? <div className="mt-1 max-w-[42ch] text-sm text-graphite">{children}</div> : null}
    </div>
  );
}
