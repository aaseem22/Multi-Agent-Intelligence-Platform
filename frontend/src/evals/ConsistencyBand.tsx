import type { CSSProperties } from "react";
import { pct } from "./lib";

interface ConsistencyBandProps {
  passRate: number | null;
  passAtK: number | null;
  passHatK: number | null;
  k: number;
}

/** Keeps an edge label inside the track: anchor left near 0, right near 100, centred otherwise. */
function anchor(value: number): CSSProperties {
  const left = `${value * 100}%`;
  if (value < 0.12) return { left, transform: "translateX(-4px)" };
  if (value > 0.88) return { left, transform: "translateX(calc(-100% + 4px))" };
  return { left, transform: "translateX(-50%)" };
}

/**
 * pass^k <= per-trial pass rate <= pass@k, drawn on one 0-100% track. The span between the two
 * outer marks is the share of tasks the system solves only sometimes: the cost of inconsistency.
 */
export function ConsistencyBand({ passRate, passAtK, passHatK, k }: ConsistencyBandProps) {
  if (passRate === null || passAtK === null || passHatK === null) return null;
  const gap = Math.max(0, passAtK - passHatK);
  const single = k <= 1;

  return (
    <figure className="space-y-2">
      <div className="relative h-5">
        <span className="absolute top-0 text-xs whitespace-nowrap text-ink-2" style={anchor(passRate)}>
          Per trial <span className="font-semibold text-ink tabular-nums">{pct(passRate)}</span>
        </span>
      </div>
      <div className="relative h-3 rounded-full bg-subtle" aria-hidden>
        {/* Solid: tasks that always pass. Hatched: tasks that pass only sometimes. */}
        <span className="absolute inset-y-0 left-0 rounded-l-full bg-ink-2" style={{ width: `${passHatK * 100}%` }} />
        {gap > 0 ? (
          <span
            className="absolute inset-y-0 border-y border-r border-ink-2/40"
            style={{
              left: `calc(${passHatK * 100}% + 2px)`,
              width: `calc(${gap * 100}% - 2px)`,
              borderTopRightRadius: 9999,
              borderBottomRightRadius: 9999,
              background:
                "repeating-linear-gradient(135deg, color-mix(in oklab, var(--color-ink-2) 38%, transparent) 0 2px, transparent 2px 6px)",
            }}
          />
        ) : null}
        <span className="absolute -top-1.5 -bottom-1.5 w-0.5 rounded-full bg-accent" style={{ left: `calc(${passRate * 100}% - 1px)` }} />
      </div>
      <div className="relative h-5 text-xs text-muted">
        {single ? (
          <span className="absolute top-0" style={anchor(passRate)}>
            pass@1 = pass^1 = pass rate
          </span>
        ) : passAtK - passHatK > 0.2 ? (
          <>
            <span className="absolute top-0 whitespace-nowrap" style={anchor(passHatK)}>
              pass^{k} <span className="font-medium text-ink tabular-nums">{pct(passHatK)}</span>
            </span>
            <span className="absolute top-0 whitespace-nowrap" style={anchor(passAtK)}>
              pass@{k} <span className="font-medium text-ink tabular-nums">{pct(passAtK)}</span>
            </span>
          </>
        ) : (
          <span className="absolute top-0 whitespace-nowrap" style={anchor((passHatK + passAtK) / 2)}>
            pass^{k} <span className="font-medium text-ink tabular-nums">{pct(passHatK)}</span> to pass@{k}{" "}
            <span className="font-medium text-ink tabular-nums">{pct(passAtK)}</span>
          </span>
        )}
      </div>
      <figcaption className="max-w-[68ch] text-sm text-muted">
        {single
          ? "With one trial per task, every measure is the same number. Run 3 or more trials to see how consistent the system is."
          : `pass@${k} counts a task if any of its ${k} trials passed; pass^${k} only if all of them did. The hatched ${pct(gap)} of tasks pass only sometimes. For a stakeholder-facing system, pass^${k} is the number to watch.`}
      </figcaption>
    </figure>
  );
}
