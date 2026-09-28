import { useEffect, useState } from "react";

// Asks the backend to check a tile's URL (see
// Source/backend/app/routes/status.py) instead of probing it from the
// browser. The backend does a real GET and reads the actual status code -
// no CORS guesswork, no mixed-content restriction, no retry-with-backoff
// dance for something a server-side request just answers directly.
export function useUrlStatus(url, intervalSeconds) {
  const [status, setStatus] = useState("pending");

  useEffect(() => {
    let cancelled = false;

    const check = () => {
      fetch(`/api/status?url=${encodeURIComponent(url)}`, { cache: "no-store" })
        .then((res) => res.json())
        .then((body) => {
          if (cancelled) return;
          setStatus(body.status === "up" || body.status === "down" ? body.status : "unknown");
        })
        .catch(() => {
          if (!cancelled) setStatus("unknown");
        });
    };

    // Stagger the first check per-tile so a full grid doesn't fire every
    // probe in the same instant.
    const startDelay = Math.floor(Math.random() * 2500);
    let interval;
    const startTimer = setTimeout(() => {
      if (cancelled) return;
      check();
      interval = setInterval(check, (intervalSeconds || 60) * 1000);
    }, startDelay);

    return () => {
      cancelled = true;
      clearTimeout(startTimer);
      if (interval) clearInterval(interval);
    };
  }, [url, intervalSeconds]);

  return status;
}
