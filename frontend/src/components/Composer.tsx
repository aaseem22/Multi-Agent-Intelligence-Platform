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
    <form onSubmit={submit} className="flex items-end gap-3 border-b-2 border-rule-strong pb-1.5 has-[textarea:focus]:border-ink">
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
        className="max-h-40 min-h-12 flex-1 resize-none bg-transparent py-1 text-base text-ink placeholder:text-pencil placeholder:italic focus:outline-none"
      />
      {streaming ? (
        <button
          type="button"
          onClick={onStop}
          className="h-9 shrink-0 rounded-xs border border-ink px-4 text-sm font-semibold text-ink hover:bg-paper-deep"
        >
          Stop
        </button>
      ) : (
        <button
          type="submit"
          disabled={!canSend}
          className="h-9 shrink-0 rounded-xs bg-ink px-4 text-sm font-semibold text-paper hover:bg-graphite disabled:cursor-not-allowed disabled:bg-rule-strong"
        >
          Ask
        </button>
      )}
    </form>
  );
}
