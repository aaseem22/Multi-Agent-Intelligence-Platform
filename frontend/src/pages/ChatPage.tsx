import { useEffect, useRef, useState } from "react";
import { A2APanel } from "../components/A2APanel";
import { Composer } from "../components/Composer";
import { ErrorState, LoadingState } from "../components/States";
import { TurnView } from "../components/TurnView";
import { useConversation } from "../hooks/useConversation";

const EXAMPLES = [
  "Which technology projects are behind schedule, and is the cause people or budget?",
  "Who is working on the repo with the most open issues, and are they over-allocated?",
  "Which department's people cost grew most last quarter?",
  "How are we doing?",
];

function Welcome({ onPick }: { onPick: (question: string) => void }) {
  return (
    <div className="pt-6 pb-10 sm:pt-12">
      <h1 className="max-w-[20ch] text-2xl font-medium tracking-tight text-balance text-ink sm:text-[2.75rem] sm:leading-[1.1]">
        Ask a question that crosses departments.
      </h1>
      <p className="mt-4 max-w-[58ch] text-base text-graphite">
        The CEO agent plans the work, hands subtasks to Finance, HR and Tech, and answers with the records behind every
        finding. When one department needs another's data it asks directly, and those messages are logged beside the
        answer as they happen.
      </p>
      <h2 className="mt-10 border-b border-rule-strong pb-1 text-sm font-semibold text-graphite">
        Questions to start with
      </h2>
      <ul>
        {EXAMPLES.map((question) => (
          <li key={question} className="border-b border-rule">
            <button type="button" onClick={() => onPick(question)} className="group w-full py-3 text-left text-lg text-ink">
              <span className="decoration-rule-strong decoration-1 underline-offset-4 group-hover:underline">
                {question}
              </span>
            </button>
          </li>
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
  if (status === "loading") body = <LoadingState label="Loading conversation" />;
  else if (status === "error")
    body = <ErrorState title="Could not load this conversation" detail={error ?? "Unknown error"} onRetry={reload} />;
  else if (turns.length === 0) body = <Welcome onPick={send} />;
  else
    body = (
      <div className="space-y-12">
        {turns.map((turn, index) => (
          <div key={turn.id} className={index > 0 ? "border-t border-rule-strong pt-10" : ""}>
            <TurnView turn={turn} />
          </div>
        ))}
      </div>
    );

  const tabClass = (active: boolean) =>
    `-mb-px border-b-2 py-2 text-sm ${active ? "border-ink font-semibold text-ink" : "border-transparent text-graphite"}`;

  return (
    <div className="grid h-full min-h-0 grid-rows-[auto_1fr] lg:grid-cols-[minmax(0,1fr)_400px] lg:grid-rows-1">
      <div
        role="tablist"
        aria-label="Answer or agent messages"
        className="flex gap-6 border-b border-rule-strong bg-paper px-4 lg:hidden"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mobileView === "chat"}
          onClick={() => setMobileView("chat")}
          className={tabClass(mobileView === "chat")}
        >
          Briefing
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mobileView === "activity"}
          onClick={() => setMobileView("activity")}
          className={tabClass(mobileView === "activity")}
        >
          Agent messages <span className="font-mono text-2xs text-pencil">{messageCount}</span>
        </button>
      </div>

      <section
        aria-label="Conversation"
        className={`${mobileView === "chat" ? "flex" : "hidden"} min-h-0 flex-col lg:flex`}
      >
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-10 sm:py-8">
          <div className="max-w-[46rem]">{body}</div>
        </div>
        <div className="bg-paper px-4 pt-2 pb-4 sm:px-10">
          <div className="max-w-[46rem]">
            <Composer streaming={streaming} onSend={send} onStop={cancel} />
          </div>
        </div>
      </section>

      <div
        className={`${mobileView === "activity" ? "flex" : "hidden"} min-h-0 flex-col border-rule lg:flex lg:border-l`}
      >
        <A2APanel turns={turns} streaming={streaming} />
      </div>
    </div>
  );
}
