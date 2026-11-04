import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Load data, and keep re-loading every `intervalMs` while `shouldPoll(data)` is true.
 *
 * Changing `key` (e.g. a filter) or calling `reload()` restarts the loop, so work queued by
 * a user action is picked up even if polling had stopped. `setData` lets callers apply a
 * fresh server response directly (e.g. the result of a mutation).
 */
export function usePolling<T>(
  load: () => Promise<T>,
  shouldPoll: (data: T) => boolean,
  key: string,
  intervalMs = 2500,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const loadRef = useRef(load);
  const pollRef = useRef(shouldPoll);
  loadRef.current = load;
  pollRef.current = shouldPoll;

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await loadRef.current();
        if (cancelled) return;
        setData(next);
        setError(null);
        if (pollRef.current(next)) timer = setTimeout(tick, intervalMs);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Request failed");
        timer = setTimeout(tick, intervalMs * 4); // back off, keep trying
      }
    };
    void tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [key, nonce, intervalMs]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, reload, setData };
}
