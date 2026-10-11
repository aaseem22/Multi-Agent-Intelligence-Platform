import { AlertTriangle, Check, ChevronRight, HelpCircle, X } from "lucide-react";
import type { ReactNode } from "react";
import type { RunStatus } from "../types/evals";
import { RUN_STATUS_LABEL, type MarkState } from "./lib";

/** Run status as a dot and a word: no pill, so it sits quietly in rows. */
export function RunStatusText({ status }: { status: RunStatus }) {
  const dot = {
    queued: "bg-faint",
    running: "live-dot",
    completed: "bg-ok",
    failed: "bg-danger",
    cancelled: "bg-line-strong",
  }[status];
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-ink-2">
      <span aria-hidden className={`size-1.5 shrink-0 rounded-full ${dot}`} />
      {RUN_STATUS_LABEL[status]}
    </span>
  );
}

const MARK_TONE: Record<MarkState, string> = {
  pass: "bg-ok-soft text-ok",
  fail: "bg-danger-soft text-danger",
  error: "bg-warn-soft text-warn",
  unknown: "bg-subtle text-muted",
};
const MARK_ICON = { pass: Check, fail: X, error: AlertTriangle, unknown: HelpCircle };
const MARK_WORD: Record<MarkState, string> = { pass: "Pass", fail: "Fail", error: "Error", unknown: "Unknown" };

/** Pass / fail / error / unknown as an icon in a tinted square. Icon shape carries the meaning; colour backs it up. */
export function Mark({ state, size = "md", label }: { state: MarkState; size?: "sm" | "md"; label?: string }) {
  const Icon = MARK_ICON[state];
  const box = size === "sm" ? "size-4 rounded-[5px]" : "size-5 rounded-md";
  return (
    <span role="img" aria-label={label ?? MARK_WORD[state]} title={label ?? MARK_WORD[state]} className={`inline-flex shrink-0 items-center justify-center ${box} ${MARK_TONE[state]}`}>
      <Icon aria-hidden size={size === "sm" ? 11 : 13} strokeWidth={2.4} />
    </span>
  );
}

/** Mark plus word, for places with room to say it. */
export function Verdict({ state, children }: { state: MarkState; children?: ReactNode }) {
  const text = { pass: "text-ok", fail: "text-danger", error: "text-warn", unknown: "text-muted" }[state];
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${text}`}>
      <Mark state={state} size="sm" label="" />
      {children ?? MARK_WORD[state]}
    </span>
  );
}

/** A thin horizontal meter: track in the subtle tone, value in the given tone, optional target tick. */
export function Meter({ value, tone = "bg-ink-2", target, label }: { value: number | null; tone?: string; target?: number; label: string }) {
  const width = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <span
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value === null ? undefined : Math.round(value * 100)}
      className="relative block h-1.5 w-full rounded-full bg-subtle"
    >
      <span className={`absolute inset-y-0 left-0 rounded-full ${tone}`} style={{ width: `${width}%` }} />
      {target !== undefined ? (
        <span aria-hidden className="absolute -top-1 -bottom-1 w-0.5 rounded-full bg-ink" style={{ left: `calc(${target * 100}% - 1px)` }} />
      ) : null}
    </span>
  );
}

/** Section heading inside a card: a title, an optional one-line explanation, optional controls. */
export function SectionHead({ title, children, actions, id }: { title: string; children?: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="min-w-0">
        <h2 id={id} className="text-base font-semibold text-ink">
          {title}
        </h2>
        {children ? <p className="mt-0.5 max-w-[68ch] text-sm text-muted">{children}</p> : null}
      </div>
      {actions}
    </header>
  );
}

/** Where you are inside the evals page, for run and trial detail. */
export function Crumbs({ items }: { items: { href?: string; label: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-sm text-muted">
      {items.map((item, i) => (
        <span key={item.label} className="inline-flex items-center gap-1">
          {i > 0 ? <ChevronRight aria-hidden size={13} strokeWidth={1.75} className="text-faint" /> : null}
          {item.href ? (
            <a href={item.href} className="rounded-sm transition-colors hover:text-ink">
              {item.label}
            </a>
          ) : (
            <span aria-current="page" className="font-medium text-ink">
              {item.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  );
}

/** A labelled figure: the number large, its name and a short meaning beneath. */
export function Figure({ value, label, note }: { value: string; label: string; note?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-2xl leading-none font-semibold tracking-tight text-ink tabular-nums">{value}</p>
      <p className="mt-1.5 text-sm font-medium text-ink-2">{label}</p>
      {note ? <p className="mt-0.5 text-xs text-muted">{note}</p> : null}
    </div>
  );
}
