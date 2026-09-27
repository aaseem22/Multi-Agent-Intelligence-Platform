import { SendHorizontal, Square } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";

interface ComposerProps {
  streaming: boolean;
  onSend: (message: string) => void;
  onStop: () => void;
}

export function Composer({ streaming, onSend, onStop }: ComposerProps) {
  const [draft, setDraft] = useState("");
  const canSend = draft.trim().length > 0 && !streaming;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSend) return;
    onSend(draft);
    setDraft("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="flex items-end gap-2 rounded-xl border border-line bg-surface p-2 shadow-sm focus-within:border-agent-tech/60">
      <label htmlFor="composer" className="sr-only">
        Ask a question across departments
      </label>
      <span id="composer-hint" className="sr-only">
        Enter sends the question. Shift and Enter adds a new line.
      </span>
      <textarea
        id="composer"
        rows={2}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask about projects, budgets or staffing"
        aria-describedby="composer-hint"
        className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] placeholder:text-faint focus:outline-none"
      />
      {streaming ? (
        <button
          type="button"
          onClick={onStop}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-medium text-ink hover:bg-paper"
        >
          <Square aria-hidden className="size-3.5 fill-current" />
          Stop
        </button>
      ) : (
        <button
          type="submit"
          disabled={!canSend}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-chrome px-3 text-sm font-medium text-white hover:bg-chrome-soft disabled:cursor-not-allowed disabled:opacity-40"
        >
          <SendHorizontal aria-hidden className="size-4" />
          Ask
        </button>
      )}
    </form>
  );
}
