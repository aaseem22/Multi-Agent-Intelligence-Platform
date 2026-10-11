import { useCallback, type PointerEvent } from "react";

/**
 * Pointer handler for `.spotlight` cards: writes the cursor position to CSS variables on the
 * element itself, so the glow follows the pointer without re-rendering React.
 */
export function useSpotlight<T extends HTMLElement>(): (event: PointerEvent<T>) => void {
  return useCallback((event: PointerEvent<T>) => {
    const element = event.currentTarget;
    const rect = element.getBoundingClientRect();
    element.style.setProperty("--mx", `${event.clientX - rect.left}px`);
    element.style.setProperty("--my", `${event.clientY - rect.top}px`);
  }, []);
}
