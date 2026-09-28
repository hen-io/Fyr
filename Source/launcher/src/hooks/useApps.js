import { useEffect, useState } from "react";

// The tile list now lives in the backend (backend-data/apps.config) instead
// of being bundled into the frontend at build time - adding/editing an app
// no longer needs a rebuild. Icon filenames come back bare (e.g. "hass.png")
// and are served by the backend at /icons/<filename>.
export function useApps() {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/apps", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((list) =>
        setApps(
          list.map((app) => ({
            ...app,
            image: app.image ? `/icons/${app.image}` : undefined,
            internalUrl: app.internalUrl ?? app.internal_url,
            defaultMode: app.defaultMode ?? app.default_mode,
          }))
        )
      )
      .catch(() => setApps([]))
      .finally(() => setLoading(false));
  }, []);

  return { apps, loading };
}
