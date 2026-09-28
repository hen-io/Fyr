import { useEffect, useState } from "react";

import { Header } from "./components/Header.jsx";
import { TileGrid } from "./components/TileGrid.jsx";
import { SettingsWindow } from "./components/SettingsWindow.jsx";
import { AppWindow } from "./components/AppWindow.jsx";
import { Footer } from "./components/Footer.jsx";
import { BackgroundEffects } from "./components/BackgroundEffects.jsx";
import { LoginModal } from "./components/LoginModal.jsx";
import { WidgetPanel } from "./components/WidgetPanel.jsx";
import { CalendarPanel } from "./components/CalendarPanel.jsx";

import { useWindowManager } from "./hooks/useWindowManager.js";
import { useAuth } from "./hooks/useAuth.js";
import { usePrefsSync } from "./hooks/usePrefsSync.js";
import { useApps } from "./hooks/useApps.js";
import { useLayout } from "./hooks/useLayout.js";
import { useWidgets } from "./hooks/useWidgets.js";

function readJSON(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}

function readTilesPerRow() {
  const saved = localStorage.getItem("launchpad-tiles");
  if (saved === "auto") return "auto";
  return Number(saved) || 4;
}

export default function App() {
  const [palette, setPalette] = useState(localStorage.getItem("launchpad-palette") || "vaporwave");
  const [bgEffect, setBgEffect] = useState(localStorage.getItem("launchpad-bg-effect") || "blobs");
  const [tilesPerRow, setTilesPerRow] = useState(readTilesPerRow);
  const [hoverEffect, setHoverEffect] = useState(localStorage.getItem("launchpad-hover-fx") || "tilt3d");
  const [openInWindow, setOpenInWindow] = useState(localStorage.getItem("launchpad-open-in-window") === "true");
  const [appPrefs, setAppPrefs] = useState(() => readJSON("launchpad-app-prefs", {}));
  const [gap, setGap] = useState(Number(localStorage.getItem("launchpad-gap")) || 12);
  const [statusInterval, setStatusInterval] = useState(Number(localStorage.getItem("launchpad-status-interval")) || 60);

  const [headerHeight, setHeaderHeight] = useState(84);
  const [headerVisible, setHeaderVisible] = useState(true);

  const [showSettings, setShowSettings] = useState(false);
  const [showLogin, setShowLogin] = useState(false);

  const { user, login, logout, changePassword } = useAuth();
  const { apps } = useApps();
  const { layout } = useLayout();
  const widgets = useWidgets();
  const { windows, openApp, closeWindow, toggleMinimize, toggleMaximize, bringToFront } = useWindowManager();
  const anyMaximized = windows.some((w) => w.maximized && !w.minimized);

  const setAppPref = (url, value) =>
    setAppPrefs((prev) => {
      const next = { ...prev };
      if (value === null) delete next[url];
      else next[url] = value;
      return next;
    });

  // When logged in, these settings follow the user across browsers/devices
  // (synced through the backend) instead of staying stuck in this browser's
  // localStorage. Anonymous visitors are unaffected - usePrefsSync is a
  // no-op without a logged-in user.
  usePrefsSync(
    user,
    { palette, bgEffect, tilesPerRow, hoverEffect, openInWindow, appPrefs, gap, statusInterval },
    (saved) => {
      if (saved.palette) setPalette(saved.palette);
      if (saved.bgEffect) setBgEffect(saved.bgEffect);
      if (saved.tilesPerRow) setTilesPerRow(saved.tilesPerRow);
      if (saved.hoverEffect) setHoverEffect(saved.hoverEffect);
      if (saved.openInWindow !== undefined) setOpenInWindow(saved.openInWindow);
      if (saved.appPrefs) setAppPrefs(saved.appPrefs);
      if (saved.gap) setGap(saved.gap);
      if (saved.statusInterval) setStatusInterval(saved.statusInterval);
    }
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-palette", palette);
    localStorage.setItem("launchpad-palette", palette);
  }, [palette]);

  useEffect(() => {
    document.documentElement.setAttribute("data-bg-effect", bgEffect);
    localStorage.setItem("launchpad-bg-effect", bgEffect);
  }, [bgEffect]);

  useEffect(() => {
    localStorage.setItem("launchpad-tiles", tilesPerRow);
  }, [tilesPerRow]);

  useEffect(() => {
    localStorage.setItem("launchpad-hover-fx", hoverEffect);
  }, [hoverEffect]);

  useEffect(() => {
    localStorage.setItem("launchpad-open-in-window", openInWindow);
  }, [openInWindow]);

  useEffect(() => {
    localStorage.setItem("launchpad-app-prefs", JSON.stringify(appPrefs));
  }, [appPrefs]);

  useEffect(() => {
    localStorage.setItem("launchpad-gap", gap);
  }, [gap]);

  useEffect(() => {
    localStorage.setItem("launchpad-status-interval", statusInterval);
  }, [statusInterval]);

  // Lock page scroll while a window fills the screen.
  useEffect(() => {
    document.body.style.overflow = anyMaximized ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [anyMaximized]);

  return (
    <div style={{ padding: gap }}>
      <BackgroundEffects effect={bgEffect} />

      <Header
        logoImage="/rocket-logo.svg"
        onToggleMenu={() => setShowSettings((v) => !v)}
        gap={gap}
        onHeight={setHeaderHeight}
        autoHide={anyMaximized}
        onVisible={setHeaderVisible}
        user={user}
        onLoginClick={() => setShowLogin(true)}
        onLogout={logout}
      />

      {showSettings && (
        <SettingsWindow
          palette={palette}
          setPalette={setPalette}
          bgEffect={bgEffect}
          setBgEffect={setBgEffect}
          hoverEffect={hoverEffect}
          setHoverEffect={setHoverEffect}
          tilesPerRow={tilesPerRow}
          setTilesPerRow={setTilesPerRow}
          openInWindow={openInWindow}
          setOpenInWindow={setOpenInWindow}
          gap={gap}
          setGap={setGap}
          statusInterval={statusInterval}
          setStatusInterval={setStatusInterval}
          apps={apps}
          appPrefs={appPrefs}
          onSetPref={setAppPref}
          onClose={() => setShowSettings(false)}
          user={user}
          onChangePassword={changePassword}
        />
      )}

      <CalendarPanel />

      <WidgetPanel widgets={widgets} />

      <TileGrid
        apps={apps}
        layout={layout}
        tilesPerRow={tilesPerRow}
        hoverEffect={hoverEffect}
        openInWindow={openInWindow}
        appPrefs={appPrefs}
        onOpenApp={openApp}
        statusInterval={statusInterval}
        disabled={anyMaximized}
        isAuthenticated={!!user}
      />

      {windows.map((w) => (
        <AppWindow
          key={w.id}
          win={w}
          onClose={() => closeWindow(w.id)}
          onMinimize={() => toggleMinimize(w.id)}
          onMaximize={() => toggleMaximize(w.id)}
          onFocus={() => bringToFront(w.id)}
          winTop={headerVisible ? headerHeight + gap * 2 : gap}
          winBottom={56 + gap * 2}
          gap={gap}
        />
      ))}

      <Footer gap={gap} windows={windows} onToggleMinimize={toggleMinimize} />

      {showLogin && <LoginModal onLogin={login} onClose={() => setShowLogin(false)} />}
    </div>
  );
}
