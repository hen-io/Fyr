import { memo, useRef, useState } from "react";
import { Mdi } from "./Icon.jsx";
import { useUrlStatus } from "../hooks/useUrlStatus.js";

export const Tile = memo(function Tile({
  title,
  url,
  internalUrl,
  image,
  mdi,
  defaultMode,
  hoverEffect,
  openInWindow,
  appPrefs,
  onOpenApp,
  statusInterval,
}) {
  const [loading, setLoading] = useState(false);

  // Resolution order: this user's per-app override (SettingsWindow's
  // "App-standarder" category) > the app's own configured default
  // (apps.config: default_mode) > the global setting. Long-press always
  // gives you whichever mode a click wouldn't - a quick escape hatch to the
  // other mode without digging into settings, rather than always forcing
  // "window" regardless of context.
  const userOverride = appPrefs?.[url];
  const appDefault = defaultMode === "window" ? true : defaultMode === "tab" ? false : undefined;
  const effectiveOpenInWindow = userOverride !== undefined ? userOverride : appDefault !== undefined ? appDefault : openInWindow;

  const openInTab = () => {
    if (loading) return;
    setLoading(true);
    setTimeout(() => {
      window.open(url, "_blank");
      setLoading(false);
    }, 500);
  };

  // Status checks use internalUrl when the app defines one (e.g. a LAN-only
  // address the backend can actually reach) - the public url still opens
  // when you click the tile either way.
  const status = useUrlStatus(internalUrl || url, statusInterval);

  const longPress = useRef(false);
  const longPressTimer = useRef(null);
  const onPointerDown = () => {
    longPress.current = false;
    longPressTimer.current = setTimeout(() => {
      longPress.current = true;
      if (effectiveOpenInWindow) openInTab();
      else onOpenApp({ title, url, image, mdi });
    }, 300);
  };
  const onPointerUp = () => clearTimeout(longPressTimer.current);

  const handleClick = (e) => {
    e.preventDefault();
    if (longPress.current) {
      longPress.current = false;
      return;
    }

    if (effectiveOpenInWindow) {
      onOpenApp({ title, url, image, mdi });
      return;
    }

    openInTab();
  };

  const useTilt = !hoverEffect || hoverEffect === "tilt3d";

  const handleMouseMove = (e) => {
    const tile = e.currentTarget;
    const rect = tile.getBoundingClientRect();
    const x = (e.clientX - rect.left - rect.width / 2) / (rect.width / 2);
    const y = (e.clientY - rect.top - rect.height / 2) / (rect.height / 2);
    tile.style.transform = `rotateX(${-y * 18}deg) rotateY(${x * 18}deg) scale(1.08)`;
  };

  const handleMouseLeave = (e) => {
    e.currentTarget.style.transform = "rotateX(0deg) rotateY(0deg) scale(1)";
  };

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", alignItems: "center" }}>
      <a
        href={url}
        onClick={handleClick}
        onMouseDown={onPointerDown}
        onMouseUp={onPointerUp}
        className={`tile tile-fx-${hoverEffect || "tilt3d"}`}
        onMouseMove={useTilt ? handleMouseMove : undefined}
        onMouseLeave={(e) => {
          onPointerUp();
          if (useTilt) handleMouseLeave(e);
        }}
        style={{
          width: "100%",
          height: "100%",
          aspectRatio: "1 / 1",
          borderRadius: "22px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          textDecoration: "none",
          userSelect: "none",
        }}
      >
        {loading ? (
          <div className="spinner"></div>
        ) : image ? (
          <img
            src={image}
            alt={title}
            className="tile-icon-img"
            draggable="false"
            style={{ userSelect: "none", pointerEvents: "none" }}
          />
        ) : mdi ? (
          <div style={{ userSelect: "none", pointerEvents: "none" }}>
            <Mdi path={mdi} size={2.5} />
          </div>
        ) : (
          <div style={{ userSelect: "none", pointerEvents: "none" }}>◆</div>
        )}

        {status !== "unknown" && (
          <span className={`tile-status-dot tile-status-dot--${status}`} title={status === "up" ? "Oppe" : status === "down" ? "Nede" : "Sjekker…"} />
        )}
      </a>

      <div
        className="tile-title-wrapper"
        style={{
          marginTop: "10px",
          height: "2.4em",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "visible",
          width: "100%",
        }}
      >
        <div
          className="tile-title"
          style={{
            fontSize: "1.25rem",
            fontWeight: 700,
            lineHeight: 1.2,
            textAlign: "center",
            padding: "0 4px",
            userSelect: "none",
            filter:
              "drop-shadow(0 1px 2px rgba(0,0,0,0.55)) " +
              "drop-shadow(0 2px 4px rgba(0,0,0,0.35)) " +
              "drop-shadow(0 0 6px rgba(0,0,0,0.25))",
          }}
        >
          {title}
        </div>
      </div>
    </div>
  );
});
