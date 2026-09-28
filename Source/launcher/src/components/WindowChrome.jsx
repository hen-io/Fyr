import { useRef } from "react";
import { useDraggable } from "../hooks/useDraggable.js";

// The standardized glass "window" shell: a draggable titlebar (icon + title
// + optional extra buttons + a close button, always last) wrapping
// arbitrary content. Every window-like popup (LoginModal, SettingsWindow,
// ...) uses this instead of hand-rolling its own titlebar markup, so they
// all look and behave identically. AppWindow (the app iframe window) has
// enough extra behavior (resize, minimize/maximize, non-draggable while
// maximized) that it keeps its own implementation, but uses the exact same
// CSS classes (app-window, app-window-titlebar, app-window-btn) so it's
// visually identical - the standardization is in the class contract, not
// just this one component.
export function WindowChrome({
  title,
  icon,
  initialPosition,
  onClose,
  extraTitlebarButtons,
  style,
  className = "",
  children,
}) {
  const windowRef = useRef(null);
  const [dragStyle, onDragStart] = useDraggable(initialPosition, windowRef);

  return (
    <div ref={windowRef} className={`glass app-window ${className}`} style={{ ...dragStyle, ...style }} onWheel={(e) => e.preventDefault()}>
      <div className="app-window-titlebar" onMouseDown={onDragStart}>
        {icon}
        <span className="app-window-title">{title}</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {extraTitlebarButtons}
          <button className="app-window-btn" onClick={onClose} title="Lukk">
            ×
          </button>
        </div>
      </div>
      {children}
    </div>
  );
}
