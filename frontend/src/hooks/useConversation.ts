import { useCallback, useEffect, useReducer, useRef } from "react";
import { backend } from "../api/backend";
import { errorMessage, isAbortError, parseServerTime } from "../lib/format";
import { emptyRun, feedFromLog, isTerminal, reduceRun, turnFromHistory, type FeedMessage, type Turn } from "../lib/run";
import type { StreamEvent } from "../types/events";

interface State {
  status: "idle" | "loading" | "error" | "ready";
  error: string | null;
  turns: Turn[];
  streaming: boolean;
}

type Action =
  | { type: "reset" }
  | { type: "load-start" }
  | { type: "loaded"; turns: Turn[] }
  | { type: "refreshed"; turns: Turn[] }
  | { type: "load-failed"; error: string }
  | { type: "turn-start"; turn: Turn }
  | { type: "event"; turnId: string; event: StreamEvent }
  | { type: "turn-end"; turnId: string; outcome: "ended" | "cancelled" | "failed"; message?: string };

const INITIAL: State = { status: "idle", error: null, turns: [], streaming: false };

function updateTurn(turns: Turn[], id: string, update: (turn: Turn) => Turn): Turn[] {
  return turns.map((turn) => (turn.id === id ? update(turn) : turn));
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "reset":
      return INITIAL;
    case "load-start":
      return { ...INITIAL, status: "loading" };
    case "loaded":
      return { ...state, status: "ready", error: null, turns: action.turns };
    case "refreshed":
      // A quiet background refresh: never replace a turn that is streaming live in this tab.
      return state.streaming ? state : { ...state, turns: action.turns };
    case "load-failed":
      return { ...state, status: "error", error: action.error };
    case "turn-start":
      return { ...state, status: "ready", streaming: true, turns: [...state.turns, action.turn] };
    case "event":
      return {
        ...state,
        turns: updateTurn(state.turns, action.turnId, (turn) => ({ ...turn, run: reduceRun(turn.run, action.event) })),
      };
    case "turn-end":
      return {
        ...state,
        streaming: false,
        turns: updateTurn(state.turns, action.turnId, (turn) => {
          if (isTerminal(turn.run.phase)) return { ...turn, live: false };
          if (action.outcome === "cancelled") return { ...turn, live: false, run: { ...turn.run, phase: "cancelled" } };
          const message =
            action.message ?? "The stream ended before an answer arrived. Check the backend logs for this request.";
          return { ...turn, live: false, run: { ...turn.run, phase: "error", error: { message, agent: null } } };
        }),
      };
  }
}

function groupByRequest(feed: FeedMessage[]): Map<string, FeedMessage[]> {
  const groups = new Map<string, FeedMessage[]>();
  for (const item of feed) {
    const list = groups.get(item.message.request_id);
    if (list) list.push(item);
    else groups.set(item.message.request_id, [item]);
  }
  return groups;
}

let localTurnCounter = 0;

/** How often to re-read a conversation whose answer is still being produced on the server. */
const PENDING_REFRESH_MS = 4000;
/** Pending turns older than this were interrupted before the server kept runs alive; stop waiting. */
const PENDING_GIVE_UP_MS = 10 * 60_000;

export function isAwaitingServer(turn: Turn, now = Date.now()): boolean {
  if (turn.live || isTerminal(turn.run.phase)) return false;
  const created = parseServerTime(turn.createdAt).getTime();
  return Number.isNaN(created) || now - created < PENDING_GIVE_UP_MS;
}

async function loadTurns(conversationId: string, signal: AbortSignal): Promise<Turn[]> {
  const [detail, log] = await Promise.all([
    backend.getConversation(conversationId, signal),
    backend.getConversationA2A(conversationId, signal),
  ]);
  const byRequest = groupByRequest(feedFromLog(log));
  return detail.turns.map((turn) => turnFromHistory(turn, byRequest.get(turn.request_id) ?? []));
}

interface Options {
  onConversationCreated: (conversationId: string) => void;
  onRunSettled: () => void;
}

export function useConversation(conversationId: string | null, { onConversationCreated, onRunSettled }: Options) {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const streamRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef<string | null>(null);
  // Set when this hook created the conversation itself, so the route change it causes
  // does not wipe the live turn by reloading from the server.
  const ownedIdRef = useRef<string | null>(null);
  const optionsRef = useRef({ onConversationCreated, onRunSettled });
  useEffect(() => {
    optionsRef.current = { onConversationCreated, onRunSettled };
  });

  const [reloadToken, reload] = useReducer((value: number) => value + 1, 0);

  useEffect(() => {
    if (conversationId !== null && conversationId === ownedIdRef.current) return;
    streamRef.current?.abort();
    ownedIdRef.current = null;

    if (conversationId === null) {
      dispatch({ type: "reset" });
      return;
    }

    const controller = new AbortController();
    dispatch({ type: "load-start" });
    loadTurns(conversationId, controller.signal).then(
      (turns) => dispatch({ type: "loaded", turns }),
      (error: unknown) => {
        if (!isAbortError(error)) dispatch({ type: "load-failed", error: errorMessage(error) });
      },
    );
    return () => controller.abort();
  }, [conversationId, reloadToken]);

  // Leaving the page only closes this tab's stream; the server finishes the answer and saves it.
  useEffect(() => () => streamRef.current?.abort(), []);

  // While an answer from an earlier visit is still being produced, re-read the conversation quietly.
  const awaiting = state.status === "ready" && !state.streaming && state.turns.some((turn) => isAwaitingServer(turn));
  useEffect(() => {
    if (!awaiting || conversationId === null) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      loadTurns(conversationId, controller.signal).then(
        (turns) => dispatch({ type: "refreshed", turns }),
        () => {
          // A failed refresh tries again on the next tick; an aborted one belongs to a page we left.
          if (!controller.signal.aborted) dispatch({ type: "refreshed", turns: [...state.turns] });
        },
      );
    }, PENDING_REFRESH_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [awaiting, conversationId, state.turns]);

  const send = useCallback(
    async (message: string) => {
      const text = message.trim();
      if (!text || streamRef.current) return;

      const controller = new AbortController();
      streamRef.current = controller;
      localTurnCounter += 1;
      const turnId = `local_${localTurnCounter}`;
      dispatch({
        type: "turn-start",
        turn: { id: turnId, question: text, createdAt: new Date().toISOString(), live: true, run: emptyRun() },
      });

      let announced = conversationId !== null;
      try {
        for await (const event of backend.streamChat({ conversation_id: conversationId, message: text }, controller.signal)) {
          dispatch({ type: "event", turnId, event });
          requestIdRef.current = event.request_id ?? requestIdRef.current;
          if (!announced && event.conversation_id) {
            announced = true;
            ownedIdRef.current = event.conversation_id;
            optionsRef.current.onConversationCreated(event.conversation_id);
          }
        }
        dispatch({ type: "turn-end", turnId, outcome: "ended" });
      } catch (error) {
        if (isAbortError(error) || controller.signal.aborted) {
          dispatch({ type: "turn-end", turnId, outcome: "cancelled" });
        } else {
          dispatch({ type: "turn-end", turnId, outcome: "failed", message: errorMessage(error) });
        }
      } finally {
        if (streamRef.current === controller) {
          streamRef.current = null;
          requestIdRef.current = null;
        }
        optionsRef.current.onRunSettled();
      }
    },
    [conversationId],
  );

  /** The Stop button: stop the run on the server, then close this tab's stream. */
  const cancel = useCallback(() => {
    const requestId = requestIdRef.current;
    if (requestId) backend.cancelChat(requestId).catch(() => undefined);
    streamRef.current?.abort();
  }, []);

  return { ...state, send, cancel, reload };
}
