import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  meta?: ReactNode;
  className?: string;
  children: ReactNode;
  labelId?: string;
}

/** An instrument panel: hairline frame, bracketed corners, a short lit tick before the title. */
export function Panel({ title, meta, className = "", children, labelId }: PanelProps) {
  return (
    <section className={`obs-panel ${className}`} aria-labelledby={labelId}>
      <span aria-hidden className="obs-corner obs-corner--tl" />
      <span aria-hidden className="obs-corner obs-corner--tr" />
      <span aria-hidden className="obs-corner obs-corner--bl" />
      <span aria-hidden className="obs-corner obs-corner--br" />
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
