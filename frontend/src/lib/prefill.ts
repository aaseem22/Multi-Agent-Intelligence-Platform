// A question handed from another page to the chat composer (for example "Ask this" on the
// Agents page). Kept in sessionStorage and read once when the chat opens.

export const PREFILL_KEY = "orchestrator.prefill";

/** Returns the waiting question, if any, and clears it so it is used once. */
export function takePrefill(): string {
  try {
    const value = window.sessionStorage.getItem(PREFILL_KEY) ?? "";
    window.sessionStorage.removeItem(PREFILL_KEY);
    return value;
  } catch {
    return "";
  }
}
