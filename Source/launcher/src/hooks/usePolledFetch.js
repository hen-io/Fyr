import { useEffect, useState } from "react";

// Polls a JSON endpoint and keeps the last successful response. Failures
// (endpoint down, network error) are swallowed - the hook just keeps
// whatever it last had, so callers can render nothing until data shows up.
export function usePolledFetch(url, intervalMs) {
  const [data, setData] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      fetch(url, { cache: "no-store" })
        .then((res) => (res.ok ? res.json() : null))
        .then((body) => {
          if (!cancelled && body) setData(body);
        })
        .catch(() => {});
    };

    load();
    const interval = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [url, intervalMs]);

  return data;
}
