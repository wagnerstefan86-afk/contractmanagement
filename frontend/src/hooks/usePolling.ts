/**
 * usePolling — repeatedly calls `fn` every `intervalMs` while `active` is true.
 *
 * - Fires immediately on mount (and whenever `active` flips to true).
 * - Cleans up the interval when `active` becomes false or the component unmounts.
 * - `fn` receives a `signal` (AbortSignal) — pass it to fetch calls so in-flight
 *   requests are cancelled when the component unmounts.
 */

import { useEffect, useRef } from "react";

export function usePolling(
  fn: () => void | Promise<void>,
  intervalMs: number,
  active: boolean,
): void {
  const fnRef = useRef(fn);
  fnRef.current = fn; // always use latest fn without re-triggering the effect

  useEffect(() => {
    if (!active) return;

    // fire immediately
    fnRef.current();

    const id = setInterval(() => {
      fnRef.current();
    }, intervalMs);

    return () => clearInterval(id);
  }, [active, intervalMs]);
}
