import { useCallback, useRef, useState } from "react";

// Tracks the set of "app windows" opened from tiles: open/focus, close,
// minimize/restore, maximize/restore. Opening a URL that's already open
// just refocuses (and un-minimizes) its existing window instead of
// duplicating it.
//
// Every action is wrapped in useCallback with no external deps (setWindows
// and the zIndex ref are both stable identities), so callers passing these
// down as props get a stable reference every render - required for
// React.memo on a receiving component (e.g. TileGrid's onOpenApp) to
// actually skip re-renders instead of always seeing a "changed" prop.
export function useWindowManager() {
  const [windows, setWindows] = useState([]);
  const zIndexRef = useRef(300);

  const bringToFront = useCallback((id) => {
    zIndexRef.current += 1;
    const z = zIndexRef.current;
    setWindows((list) => list.map((w) => (w.id === id ? { ...w, z } : w)));
  }, []);

  const openApp = useCallback((app) => {
    setWindows((list) => {
      const existing = list.find((w) => w.url === app.url);
      zIndexRef.current += 1;
      const z = zIndexRef.current;

      if (existing) {
        return list.map((w) => (w.url === app.url ? { ...w, minimized: false, z } : w));
      }

      const index = list.length;
      return [
        ...list,
        {
          ...app,
          id: `${Date.now()}${Math.random()}`,
          minimized: false,
          maximized: true,
          z,
          x0: 80 + (index % 6) * 30,
          y0: 80 + (index % 6) * 30,
        },
      ];
    });
  }, []);

  const closeWindow = useCallback((id) => setWindows((list) => list.filter((w) => w.id !== id)), []);

  const toggleMinimize = useCallback((id) => {
    zIndexRef.current += 1;
    const z = zIndexRef.current;
    setWindows((list) =>
      list.map((w) => (w.id === id ? { ...w, minimized: !w.minimized, z: w.minimized ? z : w.z } : w))
    );
  }, []);

  const toggleMaximize = useCallback(
    (id) => setWindows((list) => list.map((w) => (w.id === id ? { ...w, maximized: !w.maximized } : w))),
    []
  );

  return { windows, openApp, closeWindow, toggleMinimize, toggleMaximize, bringToFront };
}
