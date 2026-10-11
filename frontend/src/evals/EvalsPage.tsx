import { FlaskConical } from "lucide-react";
import { PageHeader } from "../components/PageHeader";
import { evalsHref, type EvalsView } from "../hooks/useHashRoute";
import { CalibrationView } from "./CalibrationView";
import { DatasetView } from "./DatasetView";
import { OverviewView } from "./OverviewView";
import { RunDetailView } from "./RunDetailView";
import { RunsView } from "./RunsView";
import { SelfEvalView } from "./SelfEvalView";
import { TrialDetailView } from "./TrialDetailView";

const TABS: { kind: EvalsView["kind"]; label: string; also?: EvalsView["kind"][] }[] = [
  { kind: "overview", label: "Overview" },
  { kind: "runs", label: "Runs", also: ["run", "trial"] },
  { kind: "calibration", label: "Calibration" },
  { kind: "self-eval", label: "Live self-evaluation" },
  { kind: "dataset", label: "Dataset" },
];

function Tabs({ view }: { view: EvalsView }) {
  return (
    <nav aria-label="Evals sections" className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <ul className="flex min-w-max gap-5 border-b border-line">
        {TABS.map((tab) => {
          const active = tab.kind === view.kind || (tab.also?.includes(view.kind) ?? false);
          return (
            <li key={tab.kind}>
              <a
                href={evalsHref({ kind: tab.kind } as EvalsView)}
                aria-current={active ? "page" : undefined}
                className={`-mb-px inline-flex h-10 items-center border-b-2 text-sm transition-colors ${
                  active ? "border-ink font-medium text-ink" : "border-transparent text-muted hover:text-ink"
                }`}
              >
                {tab.label}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function Body({ view }: { view: EvalsView }) {
  switch (view.kind) {
    case "overview":
      return <OverviewView />;
    case "runs":
      return <RunsView />;
    case "run":
      return <RunDetailView runId={view.runId} />;
    case "trial":
      return <TrialDetailView runId={view.runId} trialId={view.trialId} />;
    case "calibration":
      return <CalibrationView />;
    case "self-eval":
      return <SelfEvalView />;
    case "dataset":
      return <DatasetView />;
  }
}

export default function EvalsPage({ view }: { view: EvalsView }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-8 sm:py-12">
        <PageHeader
          icon={FlaskConical}
          title="Evals"
          description="Tasks with known answers, run several times and graded by code, a judge model and you. Below them, the reviewer that checks every live answer."
        />
        <Tabs view={view} />
        <Body view={view} />
      </div>
    </div>
  );
}
