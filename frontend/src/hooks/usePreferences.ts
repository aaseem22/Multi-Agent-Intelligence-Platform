import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

// Viewer preferences kept in localStorage: colour theme and sidebar state. Storage can be
// unavailable (private windows, blocked site data), so every access is guarded and the app
// falls back to the defaults.

export type ThemeChoice = "light" | "dark" | "system";

const THEME_KEY = "orchestrator.theme";
const SIDEBAR_KEY = "orchestrator.sidebar";
const ACTIVITY_KEY = "orchestrator.activity";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Preference is kept for this session only.
  }
}

const darkQuery = "(prefers-color-scheme: dark)";

function subscribeSystem(onChange: () => void): () => void {
  const media = window.matchMedia(darkQuery);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function readChoice(): ThemeChoice {
  const stored = read(THEME_KEY);
  return stored === "light" || stored === "dark" ? stored : "system";
}

/** Theme choice plus the theme actually shown. Applies the `dark` class to <html>. */
export function useTheme(): { choice: ThemeChoice; resolved: "light" | "dark"; setChoice: (c: ThemeChoice) => void } {
  const [choice, setChoiceState] = useState<ThemeChoice>(readChoice);
  const systemDark = useSyncExternalStore(subscribeSystem, () => window.matchMedia(darkQuery).matches);
  const resolved = choice === "system" ? (systemDark ? "dark" : "light") : choice;

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", resolved === "dark");
    // Enable colour transitions only after the first paint so the page never fades in from the wrong theme.
    const frame = requestAnimationFrame(() => root.classList.add("theme-ready"));
    return () => cancelAnimationFrame(frame);
  }, [resolved]);

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next);
    write(THEME_KEY, next);
  }, []);

  return { choice, resolved, setChoice };
}

/** Whether the desktop sidebar is collapsed to an icon rail. Toggle with Cmd/Ctrl + B. */
export function useSidebarCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => read(SIDEBAR_KEY) === "collapsed");

  const toggle = useCallback(() => {
    setCollapsed((value) => {
      write(SIDEBAR_KEY, value ? "expanded" : "collapsed");
      return !value;
    });
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
        event.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  return [collapsed, toggle];
}

/** Whether the agent-messages panel beside the chat is open. Hidden until the viewer opens it. */
export function useActivityPanel(): [boolean, (open?: boolean) => void] {
  const [open, setOpen] = useState(() => read(ACTIVITY_KEY) === "open");
  const toggle = useCallback((next?: boolean) => {
    setOpen((value) => {
      const result = next ?? !value;
      write(ACTIVITY_KEY, result ? "open" : "closed");
      return result;
    });
  }, []);
  return [open, toggle];
}
