import { useRef, useState } from "react";
import { useDraggable } from "../hooks/useDraggable.js";
import { Mdi } from "./Icon.jsx";

export function AppWindow({ win, onClose, onMinimize, onMaximize, onFocus, winTop, winBottom, gap }) {
  const windowRef = useRef(null);
  const [dragStyle, onDragStart] = useDraggable({ top: win.y0, left: win.x0 }, windowRef);
  const [size, setSize] = useState(null);
  const [loaded, setLoaded] = useState(false);

  const onResizeStart = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const rect = windowRef.current.getBoundingClientRect();
    const startX = e.clientX;
    const startY = e.clientY;
    const startWidth = rect.width;
    const startHeight = rect.height;

    const onMove = (moveEvent) => {
      setSize({
        w: Math.max(360, startWidth + (moveEvent.clientX - startX)),
        h: Math.max(260, startHeight + (moveEvent.clientY - startY)),
      });
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const sizeStyle = size ? { width: size.w, height: size.h } : { width: "min(900px, 92vw)", height: "min(640px, 82vh)" };

  const positionStyle = win.maximized
    ? {
        position: "fixed",
        top: winTop,
        left: gap,
        right: gap,
        bottom: winBottom,
        transition: "top 0.55s cubic-bezier(0.4,0,0.2,1)",
      }
    : { ...dragStyle, ...sizeStyle };

  return (
    <div
      ref={windowRef}
      className="glass app-window"
      onMouseDown={onFocus}
      onWheel={(e) => e.preventDefault()}
      style={{
        ...positionStyle,
        zIndex: win.z || 300,
        display: win.minimized ? "none" : "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div className="app-window-titlebar" onMouseDown={win.maximized ? undefined : onDragStart}>
        {win.image ? (
          <img src={win.image} alt="" className="app-window-icon" />
        ) : win.mdi ? (
          <Mdi path={win.mdi} size={0.8} />
        ) : null}

        <span className="app-window-title">{win.title}</span>

        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button className="app-window-btn" onClick={onMinimize} title="Minimer">
            –
          </button>
          <button className="app-window-btn" onClick={onMaximize} title={win.maximized ? "Gjenopprett" : "Maksimer"}>
            {win.maximized ? "🗗" : "🗖"}
          </button>
          <button className="app-window-btn" onClick={onClose} title="Lukk">
            ×
          </button>
        </div>
      </div>

      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        {!loaded && (
          <div
            className="glass-light"
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 0,
              border: "none",
            }}
          >
            <div className="spinner"></div>
          </div>
        )}
        <iframe
          src={win.url}
          className="app-window-frame"
          title={win.title}
          onLoad={() => setLoaded(true)}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", visibility: loaded ? "visible" : "hidden" }}
        />
      </div>

      {!win.maximized && <div className="app-window-resize" onMouseDown={onResizeStart} />}
    </div>
  );
}
