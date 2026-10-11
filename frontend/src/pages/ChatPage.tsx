import { ArrowUpRight, MessagesSquare, PanelRightOpen } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { A2APanel } from "../components/A2APanel";
import { AgentAvatar } from "../components/AgentName";
import { AgentOrbit } from "../components/AgentOrbit";
import { Composer } from "../components/Composer";
import { ErrorState, LoadingState } from "../components/States";
import { TurnView } from "../components/TurnView";
import { useConversation } from "../hooks/useConversation";
import { useActivityPanel } from "../hooks/usePreferences";
import { takePrefill } from "../lib/prefill";
import { useSpotlight } from "../hooks/useSpotlight";

const EXAMPLES: { question: string; agents: string[]; note: string }[] = [
  {
    question: "Which technology projects are behind schedule, and is the cause people or budget?",
    agents: ["tech", "hr", "finance"],
    note: "Three departments, with peer requests",
  },
  {
    question: "Who is working on the repo with the most open issues, and are they over-allocated?",
    agents: ["tech", "hr"],
    note: "Tech asks HR for staffing",
  },
  {
    question: "Which department's people cost grew most last quarter?",
    agents: ["finance"],
    note: "Finance on its own",
  },
  {
    question: "How are we doing?",
    agents: ["ceo"],
    note: "Too vague, so the CEO asks back",
  },
];

function ExampleCard({ example, index, onPick }: { example: (typeof EXAMPLES)[number]; index: number; onPick: (q: string) => void }) {
  const track = useSpotlight<HTMLButtonElement>();
  return (
    <li className="stagger" style={{ "--i": index + 3 } as CSSProperties}>
      <button
        type="button"
        onClick={() => onPick(example.question)}
        onPointerMove={track}
        className="spotlight group flex h-full w-full flex-col rounded-card border border-line bg-surface p-4 text-left shadow-[var(--shadow-highlight),var(--shadow-card)] transition-[border-color,box-shadow,transform] duration-300 ease-out-soft hover:-translate-y-0.5 hover:border-line-strong hover:shadow-raised active:translate-y-0"
      >
        <span className="flex items-center justify-between gap-3">
          <span className="flex -space-x-1.5">
            {example.agents.map((agent) => (
              <span key={agent} className="rounded-[8px] ring-2 ring-surface">
                <AgentAvatar name={agent} size="sm" />
              </span>
            ))}
          </span>
          <span className="inline-flex size-7 items-center justify-center rounded-full bg-subtle text-faint transition-all duration-300 ease-out-soft group-hover:bg-ink group-hover:text-on-ink">
            <ArrowUpRight aria-hidden size={14} strokeWidth={2} className="transition-transform duration-300 ease-out-soft group-hover:translate-x-px group-hover:-translate-y-px" />
          </span>
        </span>
        <span className="mt-3 text-base leading-snug font-medium text-ink">{example.question}</span>
        <span className="mt-auto pt-3 text-xs text-muted">{example.note}</span>
      </button>
    </li>
  );
}

function Welcome({ onPick }: { onPick: (question: string) => void }) {
  return (
    <div className="pt-2 pb-8 sm:pt-8">
      <section className="grid items-center gap-8 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/70 py-1 pr-3 pl-1.5 text-xs text-ink-2 shadow-card backdrop-blur stagger">
            <span className="flex -space-x-1">
              {["ceo", "finance", "hr", "tech"].map((agent) => (
                <span key={agent} className="rounded-[8px] ring-2 ring-surface">
                  <AgentAvatar name={agent} size="sm" />
                </span>
              ))}
            </span>
            Four agents, one answer
          </p>
          <h1
            className="display mt-5 pb-1 text-[1.875rem] leading-[1.12] font-semibold tracking-[-0.035em] lg:text-[2rem] stagger"
            style={{ "--i": 1 } as CSSProperties}
          >
            <span className="block">Ask one question.</span>
            <span className="block md:whitespace-nowrap">Every department answers.</span>
          </h1>
          <p className="mt-4 max-w-[46ch] text-read text-muted stagger" style={{ "--i": 2 } as CSSProperties}>
            The CEO agent plans the work, departments ask each other for what they need, and every finding links to its
            source.
          </p>
        </div>
        <div className="relative hidden md:block stagger" style={{ "--i": 2 } as CSSProperties}>
          <div
            aria-hidden
            className="absolute inset-6 rounded-full bg-[radial-gradient(circle,color-mix(in_oklab,var(--color-glow)_18%,transparent),transparent_70%)] blur-2xl"
          />
          <AgentOrbit />
        </div>
      </section>

      <h2 className="mt-10 mb-3 text-sm font-medium text-ink-2">Try one of these</h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {EXAMPLES.map((example, index) => (
          <ExampleCard key={example.question} example={example} index={index} onPick={onPick} />
        ))}
      </ul>
    </div>
  );
}

interface ChatPageProps {
  conversationId: string | null;
  onConversationCreated: (conversationId: string) => void;
  onRunSettled: () => void;
}

export function ChatPage({ conversationId, onConversationCreated, onRunSettled }: ChatPageProps) {
  const conversation = useConversation(conversationId, { onConversationCreated, onRunSettled });
  const { turns, streaming, status, error, send, cancel, reload } = conversation;
  const [mobileView, setMobileView] = useState<"chat" | "activity">("chat");
  const [panelOpen, togglePanel] = useActivityPanel();
  const [prefill] = useState(takePrefill);
  const scrollRef = useRef<HTMLDivElement>(null);

  const lastTurn = turns.at(-1);
  const progressSignal = lastTurn
    ? `${turns.length}:${lastTurn.run.phase}:${lastTurn.run.runs.length}:${lastTurn.run.messages.length}`
    : "";

  useEffect(() => {
    const element = scrollRef.current;
    if (!element || !progressSignal) return;
    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
  }, [progressSignal]);

  const messageCount = turns.reduce((sum, turn) => sum + turn.run.messages.length, 0);

  let body;
  if (status === "loading") body = <LoadingState label="Loading conversation" lines={5} />;
  else if (status === "error")
    body = <ErrorState title="Could not load this conversation" detail={error ?? "Unknown error"} onRetry={reload} />;
  else if (turns.length === 0) body = <Welcome onPick={send} />;
  else
    body = (
      <div className="space-y-12">
        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} />
        ))}
      </div>
    );

  const tabClass = (active: boolean) =>
    `flex h-8 flex-1 items-center justify-center gap-1.5 rounded-[8px] text-sm transition-colors ${
      active ? "bg-surface font-medium text-ink shadow-card" : "text-muted"
    }`;

  return (
    <div
      className={`grid h-full min-h-0 grid-rows-[auto_1fr] lg:grid-rows-1 ${
        panelOpen ? "lg:grid-cols-[minmax(0,1fr)_380px]" : "lg:grid-cols-[minmax(0,1fr)]"
      }`}
    >
      <div role="tablist" aria-label="Answer or agent messages" className="flex gap-1 border-b border-line bg-canvas p-2 lg:hidden">
        <button type="button" role="tab" aria-selected={mobileView === "chat"} onClick={() => setMobileView("chat")} className={tabClass(mobileView === "chat")}>
          Answer
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mobileView === "activity"}
          onClick={() => setMobileView("activity")}
          className={tabClass(mobileView === "activity")}
        >
          Agent messages <span className="mono-tag h-5!">{messageCount}</span>
        </button>
      </div>

      <section aria-label="Conversation" className={`${mobileView === "chat" ? "flex" : "hidden"} relative min-h-0 flex-col lg:flex`}>
        {panelOpen ? null : (
          <button
            type="button"
            onClick={() => togglePanel(true)}
            className="btn btn-secondary frost absolute top-4 right-4 z-10 hidden h-9 rounded-full! pr-3 pl-3.5 lg:inline-flex"
            aria-label={`Show agent messages (${messageCount})`}
          >
            {streaming ? <span aria-hidden className="live-dot" /> : <MessagesSquare aria-hidden size={15} strokeWidth={1.75} />}
            Agent messages
            <span className="mono-tag h-5!">{messageCount}</span>
            <PanelRightOpen aria-hidden size={15} strokeWidth={1.75} className="text-faint" />
          </button>
        )}
        {/* Content fades out above the composer through a mask, so nothing is painted over the background. */}
        <div
          ref={scrollRef}
          className={`min-h-0 flex-1 overflow-y-auto px-4 pt-6 pb-6 sm:px-8 sm:pt-8 mask-[linear-gradient(to_bottom,black_calc(100%-2.5rem),transparent)] ${
            panelOpen ? "" : "lg:pt-16"
          }`}
        >
          <div className="mx-auto max-w-3xl">{body}</div>
        </div>
        <div className="px-4 pt-1 pb-4 sm:px-8 sm:pb-6">
          <div className="mx-auto max-w-3xl">
            <Composer streaming={streaming} initialDraft={prefill} onSend={send} onStop={cancel} />
          </div>
        </div>
      </section>

      <div
        className={`${mobileView === "activity" ? "flex" : "hidden"} min-h-0 flex-col border-line lg:border-l ${
          panelOpen ? "lg:flex lg:animate-slide-in" : "lg:hidden"
        }`}
      >
        <A2APanel turns={turns} streaming={streaming} onClose={() => togglePanel(false)} />
      </div>
    </div>
  );
}
