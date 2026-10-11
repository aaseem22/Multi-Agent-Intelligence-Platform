import { ArrowUp, Square } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";

interface ComposerProps {
  streaming: boolean;
  /** Text to start with, e.g. a question picked on the Agents page. */
  initialDraft?: string;
  onSend: (message: string) => void;
  onStop: () => void;
}

export function Composer({ streaming, initialDraft = "", onSend, onStop }: ComposerProps) {
  const [draft, setDraft] = useState(initialDraft);
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
    <form
      onSubmit={submit}
      className="glow-focus rounded-card border border-line bg-surface p-2 shadow-[var(--shadow-highlight),var(--shadow-composer)] transition-[border-color,box-shadow] duration-200 has-[textarea:focus]:border-transparent"
    >
      <label htmlFor="composer" className="sr-only">
        Ask a question across departments
      </label>
      <textarea
        id="composer"
        autoFocus={initialDraft.length > 0}
        rows={2}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask about projects, budgets or staffing"
        aria-describedby="composer-hint"
        className="block max-h-40 min-h-14 w-full resize-none bg-transparent px-2.5 pt-1.5 text-read text-ink placeholder:text-faint focus:outline-none"
      />
      <div className="flex items-center justify-between gap-3 pl-2.5">
        <p id="composer-hint" className="hidden text-2xs text-faint sm:block">
          <kbd className="mono-tag h-5!">Enter</kbd> to send, <kbd className="mono-tag h-5!">Shift</kbd> +{" "}
          <kbd className="mono-tag h-5!">Enter</kbd> for a new line
        </p>
        {streaming ? (
          <button type="button" onClick={onStop} className="btn btn-secondary ml-auto h-9">
            <Square aria-hidden size={12} strokeWidth={0} fill="currentColor" />
            Stop
          </button>
        ) : (
          <button type="submit" disabled={!canSend} className="btn btn-primary ml-auto h-9" aria-label="Ask">
            Ask
            <ArrowUp aria-hidden size={15} strokeWidth={2} />
          </button>
        )}
      </div>
    </form>
  );
}
