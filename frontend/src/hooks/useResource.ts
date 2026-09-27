import { useCallback, useEffect, useState } from "react";
import { errorMessage, isAbortError } from "../lib/format";

export type Resource<T> =
  | { status: "loading"; data: T | null }
  | { status: "error"; data: T | null; error: string }
  | { status: "ready"; data: T };

/**
 * Loads data with an abortable fetcher. `key` changes trigger a reload; `reload()`
 * refetches in place and keeps the previous data visible while it runs.
 */
export function useResource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  key: string,
): [Resource<T>, () => void] {
  const [state, setState] = useState<Resource<T>>({ status: "loading", data: null });
  const [attempt, setAttempt] = useState(0);
  const [loadedKey, setLoadedKey] = useState(key);

  // Reset synchronously when the key changes so stale data from another key never shows.
  if (loadedKey !== key) {
    setLoadedKey(key);
    setState({ status: "loading", data: null });
  }

  useEffect(() => {
    const controller = new AbortController();
    fetcher(controller.signal).then(
      (data) => setState({ status: "ready", data }),
      (error: unknown) => {
        if (isAbortError(error)) return;
        setState((previous) => ({ status: "error", data: previous.data, error: errorMessage(error) }));
      },
    );
    return () => controller.abort();
    // fetcher identity is intentionally ignored; key and attempt drive reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const reload = useCallback(() => {
    setState((previous) => ({ status: "loading", data: previous.data }));
    setAttempt((value) => value + 1);
  }, []);

  return [state, reload];
}
