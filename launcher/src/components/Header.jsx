import { useEffect, useRef, useState } from "react";
import { Mdi } from "./Icon.jsx";
import { mdiAccount, mdiMenu } from "@mdi/js";

export function Header({ onToggleMenu, logoImage, logoIcon, gap, onHeight, autoHide, onVisible, user, onLoginClick, onLogout }) {
  const [hovering, setHovering] = useState(false);
  const headerRef = useRef(null);

  // Report our own height so the caller can position windows/panels below us.
  useEffect(() => {
    if (!headerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      onHeight(entries[0].contentRect.height + 20);
    });
    observer.observe(headerRef.current);
    return () => observer.disconnect();
  }, [onHeight]);

  useEffect(() => {
    onVisible?.(!autoHide || hovering);
  }, [autoHide, hovering, onVisible]);

  // When auto-hide is on (a window is maximized), slide the header away and
  // only reveal it again while the mouse is near the top edge or over the
  // header itself - with a short grace period so it doesn't flicker.
  useEffect(() => {
    if (!autoHide) return;

    let lastNear = 0;
    let over = false;
    let rafPending = false;

    // getBoundingClientRect() forces a layout read - fine once per frame,
    // wasteful at raw mousemove frequency (which can fire far faster than
    // the display refreshes). rAF-gating collapses a burst of events down
    // to at most one check per painted frame.
    const checkPosition = (e) => {
      rafPending = false;
      const rect = headerRef.current && headerRef.current.getBoundingClientRect();
      const near =
        e.clientY <= 10 ||
        (rect && e.clientY >= rect.top && e.clientY <= rect.bottom + 4 && e.clientX >= rect.left && e.clientX <= rect.right);
      if (near) {
        lastNear = performance.now();
        setHovering(true);
      }
    };

    const onMouseMove = (e) => {
      if (rafPending) return;
      rafPending = true;
      requestAnimationFrame(() => checkPosition(e));
    };

    const onEnter = () => {
      over = true;
      lastNear = performance.now();
      setHovering(true);
    };
    const onLeave = () => {
      over = false;
    };

    const el = headerRef.current;
    el?.addEventListener("mouseenter", onEnter);
    el?.addEventListener("mouseleave", onLeave);

    const interval = setInterval(() => {
      if (!over && performance.now() - lastNear > 500) setHovering(false);
    }, 200);

    window.addEventListener("mousemove", onMouseMove);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      el?.removeEventListener("mouseenter", onEnter);
      el?.removeEventListener("mouseleave", onLeave);
      clearInterval(interval);
    };
  }, [autoHide]);

  return (
    <header
      ref={headerRef}
      className="glass-light"
      onWheel={(e) => e.preventDefault()}
      style={{
        padding: "10px 20px",
        display: "flex",
        alignItems: "center",
        marginBottom: gap,
        position: "sticky",
        top: gap,
        zIndex: 50,
        transform: autoHide && !hovering ? "translateY(-140%)" : "translateY(0)",
        transition: "transform 0.55s cubic-bezier(0.4,0,0.2,1)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {logoImage ? (
          <img src={logoImage} alt="Fyr" style={{ width: 32, height: 32, borderRadius: 8 }} />
        ) : logoIcon ? (
          <Mdi path={logoIcon} size={1.4} />
        ) : null}

        <h2 style={{ margin: 0 }}>Fyr</h2>
      </div>

      <button
        onClick={user ? onLogout : onLoginClick}
        title={user ? `Logget inn som ${user.username} - klikk for å logge ut` : "Logg inn"}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 6,
          userSelect: "none",
          marginLeft: "auto",
          color: "var(--text)",
        }}
      >
        <Mdi path={mdiAccount} size={1.2} color="var(--text)" />
        {user && <span style={{ fontSize: "0.85rem" }}>{user.username}</span>}
      </button>

      <button
        onClick={onToggleMenu}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          marginLeft: 14,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          userSelect: "none",
        }}
      >
        <Mdi path={mdiMenu} size={1.5} color="var(--text)" />
      </button>
    </header>
  );
}
