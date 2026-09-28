import { useMemo, useState } from "react";
import { WindowChrome } from "./WindowChrome.jsx";
import { BACKGROUND_EFFECTS, HOVER_EFFECTS, PALETTES } from "../constants/appearance.js";
import { APP_AUTHOR, APP_COPYRIGHT_YEAR, APP_HOMEPAGE, APP_VERSION } from "../constants/appInfo.js";

const CATEGORIES = ["Utseende", "Apper", "Avansert", "Konto", "Om"];

const PASSWORD_ERRORS = {
  wrong_current_password: "Feil nåværende passord.",
  password_too_short: "Det nye passordet må være minst 8 tegn.",
  too_many_attempts: "For mange forsøk. Vent litt og prøv igjen.",
  not_authenticated: "Du må være logget inn.",
};

function ChangePasswordForm({ onChangePassword }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [status, setStatus] = useState(null); // { type: "error"|"success", text }
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setStatus(null);

    if (newPassword.length < 8) {
      setStatus({ type: "error", text: PASSWORD_ERRORS.password_too_short });
      return;
    }
    if (newPassword !== confirmPassword) {
      setStatus({ type: "error", text: "De nye passordene er ikke like." });
      return;
    }

    setSubmitting(true);
    try {
      await onChangePassword(currentPassword, newPassword);
      setStatus({ type: "success", text: "Passord endret." });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setStatus({ type: "error", text: PASSWORD_ERRORS[err.message] || "Kunne ikke endre passord." });
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle = {
    width: "100%",
    padding: "8px 12px",
    borderRadius: 10,
    border: "1px solid rgba(255,255,255,0.18)",
    background: "rgba(255,255,255,0.08)",
    color: "var(--text)",
    marginBottom: 10,
  };

  return (
    <form onSubmit={handleSubmit} style={{ maxWidth: 320 }}>
      <input
        type="password"
        placeholder="Nåværende passord"
        value={currentPassword}
        onChange={(e) => setCurrentPassword(e.target.value)}
        autoComplete="current-password"
        style={inputStyle}
      />
      <input
        type="password"
        placeholder="Nytt passord (min. 8 tegn)"
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
        autoComplete="new-password"
        style={inputStyle}
      />
      <input
        type="password"
        placeholder="Bekreft nytt passord"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        autoComplete="new-password"
        style={inputStyle}
      />
      {status && (
        <p style={{ color: status.type === "error" ? "#fab219" : "#3fbf7f", fontSize: "0.85rem", marginTop: -2 }}>
          {status.text}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting || !currentPassword || !newPassword}
        style={{
          padding: "8px 16px",
          borderRadius: 10,
          border: "none",
          cursor: submitting ? "default" : "pointer",
          background: "rgba(255,255,255,0.16)",
          color: "var(--text)",
          opacity: submitting ? 0.6 : 1,
        }}
      >
        {submitting ? "Endrer..." : "Endre passord"}
      </button>
    </form>
  );
}

export function SettingsWindow({
  palette,
  setPalette,
  bgEffect,
  setBgEffect,
  hoverEffect,
  setHoverEffect,
  tilesPerRow,
  setTilesPerRow,
  openInWindow,
  setOpenInWindow,
  gap,
  setGap,
  statusInterval,
  setStatusInterval,
  apps,
  appPrefs,
  onSetPref,
  onClose,
  user,
  onChangePassword,
}) {
  const [category, setCategory] = useState("Utseende");
  const [search, setSearch] = useState("");

  // A flat registry of every setting, so search can filter across
  // categories instead of only within whichever one is selected. Each
  // entry's `label` is what search matches against; `render` closes over
  // the props above rather than needing its own prop-threading.
  const registry = useMemo(
    () => [
      {
        id: "bg-effect",
        category: "Utseende",
        label: "Bakgrunnseffekt",
        render: () => (
          <div className="theme-select">
            <select value={bgEffect} onChange={(e) => setBgEffect(e.target.value)}>
              {BACKGROUND_EFFECTS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        ),
      },
      {
        id: "palette",
        category: "Utseende",
        label: "Fargepalett",
        render: () => (
          <div className="theme-select">
            <select value={palette} onChange={(e) => setPalette(e.target.value)}>
              {PALETTES.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        ),
      },
      {
        id: "hover-effect",
        category: "Utseende",
        label: "Hover-effekt",
        render: () => (
          <div className="theme-select">
            <select value={hoverEffect} onChange={(e) => setHoverEffect(e.target.value)}>
              {HOVER_EFFECTS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        ),
      },
      {
        id: "tiles-per-row",
        category: "Apper",
        label: "Fliser per rad",
        render: () => (
          <div className="theme-select">
            <select value={tilesPerRow} onChange={(e) => setTilesPerRow(e.target.value === "auto" ? "auto" : Number(e.target.value))}>
              <option value="auto">Auto (rullefelt per kategori)</option>
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        ),
      },
      {
        id: "open-in-window",
        category: "Apper",
        label: "Åpne apper i vindu",
        render: () => (
          <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
            <input type="checkbox" checked={openInWindow} onChange={(e) => setOpenInWindow(e.target.checked)} />
            Åpne apper i vindu (globalt standardvalg)
          </label>
        ),
      },
      {
        id: "app-defaults",
        category: "Apper",
        label: "App-standarder per app",
        render: () => (
          <div>
            <p style={{ fontSize: "0.8rem", opacity: 0.7, marginTop: 0, marginBottom: 12 }}>
              Overstyr &quot;Åpne apper i vindu&quot; per app. Langt trykk på en flis åpner alltid i motsatt modus.
            </p>
            {apps.map((app) => (
              <div className="app-pref-row" key={app.title}>
                {app.image ? <img src={app.image} className="app-pref-icon" alt="" /> : null}
                <span className="app-pref-name">{app.title}</span>
                <select
                  className="app-pref-select"
                  value={appPrefs[app.url] === undefined ? "default" : appPrefs[app.url] ? "window" : "tab"}
                  onChange={(e) => {
                    const v = e.target.value;
                    onSetPref(app.url, v === "default" ? null : v === "window");
                  }}
                >
                  <option value="default">Standard</option>
                  <option value="window">Vindu</option>
                  <option value="tab">Ny fane</option>
                </select>
              </div>
            ))}
          </div>
        ),
      },
      {
        id: "gap",
        category: "Avansert",
        label: "Avstand/marg",
        render: () => (
          <>
            <label style={{ display: "block", marginBottom: 4 }}>Avstand/marg: {gap}px</label>
            <input type="range" min="8" max="48" value={gap} onChange={(e) => setGap(Number(e.target.value))} style={{ width: "100%" }} />
          </>
        ),
      },
      {
        id: "status-interval",
        category: "Avansert",
        label: "Statussjekk-intervall",
        render: () => (
          <>
            <label style={{ display: "block", marginBottom: 4 }}>Statussjekk-intervall: {statusInterval}s</label>
            <input
              type="range"
              min="15"
              max="300"
              step="15"
              value={statusInterval}
              onChange={(e) => setStatusInterval(Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </>
        ),
      },
      ...(user
        ? [
            {
              id: "change-password",
              category: "Konto",
              label: "Endre passord",
              render: () => <ChangePasswordForm onChangePassword={onChangePassword} />,
            },
          ]
        : []),
      {
        id: "about",
        category: "Om",
        label: "Om Fyr",
        render: () => (
          <div style={{ textAlign: "center" }}>
            <img
              src="/rocket-logo.svg"
              alt="Fyr"
              style={{
                width: "88px",
                height: "88px",
                marginBottom: "14px",
                userSelect: "none",
                filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.55)) drop-shadow(0 2px 4px rgba(0,0,0,0.35))",
              }}
            />
            <h1 style={{ margin: "0 0 6px 0", fontSize: "1.6rem" }}>Fyr</h1>
            <h3 style={{ margin: "0 0 10px 0", fontSize: "1rem", opacity: 0.75 }}>Av {APP_AUTHOR}</h3>
            <h4 style={{ margin: "0 0 10px 0", fontSize: "1rem", opacity: 0.6 }}>{APP_HOMEPAGE}</h4>
            <h4 style={{ margin: "0 0 10px 0", fontSize: "0.8rem", opacity: 0.8 }}>Version {APP_VERSION}</h4>
            <p style={{ margin: 0, opacity: 0.7, fontSize: "0.9rem" }}>© {APP_COPYRIGHT_YEAR} Fyr services</p>
          </div>
        ),
      },
    ],
    [
      palette,
      bgEffect,
      hoverEffect,
      tilesPerRow,
      openInWindow,
      gap,
      statusInterval,
      apps,
      appPrefs,
      setPalette,
      setBgEffect,
      setHoverEffect,
      setTilesPerRow,
      setOpenInWindow,
      setGap,
      setStatusInterval,
      onSetPref,
      user,
      onChangePassword,
    ]
  );

  const categories = user ? CATEGORIES : CATEGORIES.filter((c) => c !== "Konto");
  const activeCategory = categories.includes(category) ? category : categories[0];

  const query = search.trim().toLowerCase();
  const visible = query
    ? registry.filter((item) => item.label.toLowerCase().includes(query) || item.category.toLowerCase().includes(query))
    : registry.filter((item) => item.category === activeCategory);

  return (
    <WindowChrome
      title="Innstillinger"
      onClose={onClose}
      initialPosition={{ top: "50%", left: "50%", transform: "translate(-50%, -50%)" }}
      style={{
        width: "min(640px, 92vw)",
        height: "min(480px, 80vh)",
        zIndex: 999,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div style={{ padding: "12px 16px 0" }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Søk i innstillinger..."
          style={{
            width: "100%",
            padding: "8px 12px",
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,0.18)",
            background: "rgba(255,255,255,0.08)",
            color: "var(--text)",
          }}
        />
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {!query && (
          <div style={{ width: 140, flexShrink: 0, padding: 16, borderRight: "1px solid rgba(255,255,255,0.1)" }}>
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 10px",
                  marginBottom: 4,
                  borderRadius: 8,
                  border: "none",
                  cursor: "pointer",
                  background: activeCategory === cat ? "rgba(255,255,255,0.14)" : "transparent",
                  color: "var(--text)",
                }}
              >
                {cat}
              </button>
            ))}
          </div>
        )}

        <div style={{ flex: 1, padding: 20, overflowY: "auto", overscrollBehavior: "contain" }}>
          {visible.length === 0 && <p style={{ opacity: 0.6 }}>Ingen treff.</p>}
          {visible.map((item) => (
            <div key={item.id} style={{ marginBottom: 24 }}>
              {query && (
                <div style={{ fontSize: "0.75rem", opacity: 0.6, marginBottom: 4, textTransform: "uppercase" }}>
                  {item.category}
                </div>
              )}
              <div style={{ marginBottom: 8, fontWeight: 600, fontSize: "0.95rem" }}>{item.label}</div>
              {item.render()}
            </div>
          ))}
        </div>
      </div>
    </WindowChrome>
  );
}
