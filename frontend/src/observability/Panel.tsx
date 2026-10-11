import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  meta?: ReactNode;
  className?: string;
  children: ReactNode;
  labelId?: string;
}

/** A dashboard card with a title row and optional meta on the right. */
export function Panel({ title, meta, className = "", children, labelId }: PanelProps) {
  return (
    <section className={`obs-panel animate-enter ${className}`} aria-labelledby={labelId}>
      <header className="obs-panel-head">
        <h2 id={labelId} className="obs-panel-title">
          {title}
        </h2>
        {meta ? <div className="obs-panel-meta">{meta}</div> : null}
      </header>
      {children}
    </section>
  );
}
