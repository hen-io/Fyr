import { useEffect, useRef } from "react";

// When logged in, pulls this user's saved prefs once (per login) and
// applies them via `applyPrefs`, then pushes any local change back to the
// backend (debounced, so dragging a slider doesn't fire a request per
// pixel). A no-op for anonymous visitors - their prefs stay
// localStorage-only, exactly as before this existed.
export function usePrefsSync(user, prefs, applyPrefs) {
  const loadedForUser = useRef(null);
  const debounceRef = useRef(null);
  const skipNextPush = useRef(false);

  useEffect(() => {
    if (!user) {
      loadedForUser.current = null;
      return;
    }
    if (loadedForUser.current === user.username) return;
    loadedForUser.current = user.username;

    fetch("/api/me/prefs", { credentials: "same-origin" })
      .then((res) => (res.ok ? res.json() : null))
      .then((saved) => {
        if (saved && Object.keys(saved).length > 0) {
          skipNextPush.current = true;
          applyPrefs(saved);
        }
      })
      .catch(() => {});
    // applyPrefs is stable enough in practice (defined once in App); only
    // re-run this when the logged-in user actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    if (!user) return;
    if (skipNextPush.current) {
      skipNextPush.current = false;
      return;
    }

    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetch("/api/me/prefs", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(prefs),
      }).catch(() => {});
    }, 800);

    return () => clearTimeout(debounceRef.current);
    // `prefs` is a fresh object every render - depend on its serialized
    // form so this only actually fires when a value inside it changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, JSON.stringify(prefs)]);
}
