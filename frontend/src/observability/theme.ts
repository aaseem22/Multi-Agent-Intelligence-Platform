// Scoped tokens and formatters for the observability dashboard. Agent hues were validated with
// the dataviz palette checker against the panel surface (#0a111c, dark, all pairs): lightness
// band, chroma, CVD separation (worst ΔE 8.1) and normal-vision floor (16.2) all pass.

const AGENT_HUE: Record<string, string> = {
  tech: "#1f9fd2",
  finance: "#8a70f0",
  hr: "#d9589a",
};
const SUPERVISOR_HUE = "#e6f5ff";
/** Departments registered later share a neutral hue; their names are always labelled. */
const OVERFLOW_HUE = "#8fa6b6";

export function agentHue(name: string, supervisor: string | null = "ceo"): string {
  if (name === supervisor) return SUPERVISOR_HUE;
  return AGENT_HUE[name] ?? OVERFLOW_HUE;
}

const LABELS: Record<string, string> = { ceo: "CEO", hr: "HR" };

export function agentName(name: string): string {
  return LABELS[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
}

const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function formatInt(value: number): string {
  return integer.format(value);
}

export function formatCompact(value: number): string {
  return value >= 10_000 ? compact.format(value) : integer.format(value);
}

export function formatSeconds(ms: number | null | undefined, digits = 1): string {
  if (ms == null) return "–";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(digits)} s`;
}

export function formatPercent(ratio: number | null | undefined, digits = 0): string {
  if (ratio == null) return "–";
  return `${(ratio * 100).toFixed(digits)}%`;
}

export function formatCost(value: number | null | undefined): string {
  if (value == null) return "–";
  if (value === 0) return "$0";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto", style: "short" });

export function formatAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "";
  const seconds = Math.round((at - now) / 1000);
  if (Math.abs(seconds) < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return relative.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return relative.format(hours, "hour");
  return relative.format(Math.round(hours / 24), "day");
}

const dayLabel = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
const hourLabel = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const stamp = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function formatBucket(iso: string, bucket: "hour" | "day"): string {
  const date = new Date(iso);
  return bucket === "hour" ? `${dayLabel.format(date)}, ${hourLabel.format(date)}` : dayLabel.format(date);
}

export function formatStamp(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : stamp.format(date);
}

export function scoreLabel(name: string): string {
  const stage = name.replace(/^eval_/, "");
  return stage.charAt(0).toUpperCase() + stage.slice(1);
}
