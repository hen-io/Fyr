import { useEffect, useState } from "react";

// The list of configured widgets (backend-data/ui.conf) - rarely changes,
// fetched once. Each widget's live value is polled separately by the
// component that renders it (see GaugeWidget.jsx), same split as
// apps (list) vs status (per-tile polled value).
export function useWidgets() {
  const [widgets, setWidgets] = useState([]);

  useEffect(() => {
    fetch("/api/widgets", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then(setWidgets)
      .catch(() => setWidgets([]));
  }, []);

  return widgets;
}
