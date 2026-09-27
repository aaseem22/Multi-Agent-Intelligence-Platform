import { MessagesSquare, Network } from "lucide-react";
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
    <div className="mx-auto max-w-2xl py-10">
      <h1 className="text-2xl leading-tight font-semibold tracking-tight text-ink">
        Ask a question that crosses departments.
      </h1>
      <p className="mt-2 max-w-[60ch] text-muted">
        The CEO agent plans the work, sends subtasks to Finance, HR and Tech, and answers with the records behind every
        claim. Requests between departments show up in the activity panel as they happen.
      </p>
      <ul className="mt-6 space-y-2">
        {EXAMPLES.map((question) => (
          <li key={question}>
            <button
              type="button"
              onClick={() => onPick(question)}
              className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-left text-[15px] text-ink hover:border-agent-tech/50"
            >
              {question}
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
      <div className="mx-auto max-w-3xl space-y-10">
        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} />
        ))}
      </div>
    );

  return (
    <div className="grid h-full min-h-0 grid-rows-[auto_1fr] lg:grid-cols-[minmax(0,1fr)_380px] lg:grid-rows-1">
      <div
        role="tablist"
        aria-label="Chat or activity"
        className="flex gap-1 border-b border-line bg-surface px-3 py-2 lg:hidden"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mobileView === "chat"}
          onClick={() => setMobileView("chat")}
          className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium ${
            mobileView === "chat" ? "bg-chrome text-white" : "text-muted"
          }`}
        >
          <MessagesSquare aria-hidden className="size-4" />
          Chat
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mobileView === "activity"}
          onClick={() => setMobileView("activity")}
          className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium ${
            mobileView === "activity" ? "bg-chrome text-white" : "text-muted"
          }`}
        >
          <Network aria-hidden className="size-4" />
          Activity ({messageCount})
        </button>
      </div>

      <section
        aria-label="Conversation"
        className={`${mobileView === "chat" ? "flex" : "hidden"} min-h-0 flex-col lg:flex`}
      >
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          {body}
        </div>
        <div className="border-t border-line bg-paper px-4 py-3 sm:px-8">
          <div className="mx-auto max-w-3xl">
            <Composer streaming={streaming} onSend={send} onStop={cancel} />
          </div>
        </div>
      </section>

      <div
        className={`${mobileView === "activity" ? "flex" : "hidden"} min-h-0 flex-col border-line lg:flex lg:border-l`}
      >
        <A2APanel turns={turns} streaming={streaming} />
      </div>
    </div>
  );
}
