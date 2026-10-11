import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface PageHeaderProps {
  icon: LucideIcon;
  title: string;
  description: ReactNode;
  actions?: ReactNode;
}

/** Shared page header: an accent icon tile, the title, one line of context, and optional controls. */
export function PageHeader({ icon: Icon, title, description, actions }: PageHeaderProps) {
  return (
    <header className="flex flex-wrap items-end gap-x-6 gap-y-4 animate-enter">
      <div className="flex min-w-0 flex-1 items-start gap-4">
        <span className="mt-1 inline-flex size-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent ring-1 ring-accent/15">
          <Icon aria-hidden size={20} strokeWidth={1.75} />
        </span>
        <div className="min-w-0">
          <h1 className="display pb-0.5 text-2xl font-semibold tracking-[-0.03em] sm:text-[2.125rem] sm:leading-[2.5rem]">{title}</h1>
          <p className="mt-1 max-w-[62ch] text-read text-muted">{description}</p>
        </div>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-x-4 gap-y-2">{actions}</div> : null}
    </header>
  );
}
