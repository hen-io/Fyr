import { Mdi } from "./Icon.jsx";
import { useClock } from "../hooks/useClock.js";
import { usePolledFetch } from "../hooks/usePolledFetch.js";
import { APP_COPYRIGHT_YEAR } from "../constants/appInfo.js";

// Clock/weather/home-status all live here rather than in App state - they
// change every few seconds to minutes, and keeping them local to the one
// component that renders them means a tick doesn't re-render the header,
// the tile grid, or the background effect.
export function Footer({ gap, windows, onToggleMinimize }) {
  const clock = useClock();
  const weather = usePolledFetch("/api/weather", 300000);
  const homeStatus = usePolledFetch("/api/home", 60000);

  return (
    <footer className="app-footer glass-light" onWheel={(e) => e.preventDefault()} style={{ left: gap, right: gap, bottom: gap }}>
      <span className="app-footer-copy">©{APP_COPYRIGHT_YEAR} Fyr services inc</span>

      {windows.length > 0 && (
        <div className="win-dock">
          {windows.map((w) => (
            <button
              key={w.id}
              className={`win-dock-chip${w.minimized ? "" : " win-dock-chip--active"}`}
              onClick={() => onToggleMinimize(w.id)}
              title={w.title}
            >
              {w.image ? (
                <img src={w.image} className="win-dock-icon" alt="" />
              ) : w.mdi ? (
                <Mdi path={w.mdi} size={0.7} />
              ) : null}
              <span className="win-dock-label">{w.title}</span>
            </button>
          ))}
        </div>
      )}

      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
        {homeStatus && (
          <div className="header-chip" title="Hjem-modus">
            <svg viewBox="0 0 24 24" width={15} height={15} fill="currentColor" style={{ opacity: 0.9, flexShrink: 0 }}>
              <path d="M12 3l9 8h-3v9h-5v-6h-2v6H6v-9H3l9-8z" />
            </svg>
            <span>{homeStatus.mode}</span>
          </div>
        )}

        {homeStatus && homeStatus.indoor_temperature != null && (
          <div className="header-chip" title="Innendørstemperatur">
            <span style={{ fontSize: "1rem", lineHeight: 1 }}>🌡️</span>
            <span>{homeStatus.indoor_temperature}°</span>
          </div>
        )}

        {weather && (
          <div className="header-chip" title={weather.condition}>
            <span style={{ fontSize: "1.1rem", lineHeight: 1 }}>{weather.icon}</span>
            <span>{weather.temperature != null ? Math.round(weather.temperature) : "–"}°</span>
          </div>
        )}

        {clock.time && <span style={{ fontSize: "1.5rem", fontWeight: 600, userSelect: "none" }}>{clock.time}</span>}
      </div>
    </footer>
  );
}
