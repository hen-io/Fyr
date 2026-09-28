import { useEffect, useState } from "react";

// backend-data/ui.conf, keyed by tile title -> {x, y, w, h} in grid units.
// Empty by default - TileGrid falls back to its normal auto-flow,
// grouped-by-category layout when this has no entries.
export function useLayout() {
  const [layout, setLayout] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/layout", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : {}))
      .then(setLayout)
      .catch(() => setLayout({}))
      .finally(() => setLoading(false));
  }, []);

  return { layout, loading };
}
