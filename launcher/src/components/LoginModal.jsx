import { useState } from "react";
import { WindowChrome } from "./WindowChrome.jsx";

export function LoginModal({ onLogin, onClose }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onLogin(username, password);
      onClose();
    } catch {
      setError("Feil brukernavn eller passord.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <WindowChrome
      title="Logg inn"
      initialPosition={{ top: "50%", left: "50%", transform: "translate(-50%, -50%)" }}
      onClose={onClose}
      style={{ width: "min(340px, 92vw)", zIndex: 200, display: "flex", flexDirection: "column", overflow: "hidden" }}
    >
      <form onSubmit={handleSubmit} style={{ padding: 24 }}>
        <label style={{ display: "block", marginBottom: 4 }}>Brukernavn</label>
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
          style={{
            width: "100%",
            marginBottom: 16,
            padding: "8px 10px",
            borderRadius: 8,
            border: "1px solid rgba(255,255,255,0.2)",
            background: "rgba(255,255,255,0.08)",
            color: "var(--text)",
          }}
        />

        <label style={{ display: "block", marginBottom: 4 }}>Passord</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{
            width: "100%",
            marginBottom: 16,
            padding: "8px 10px",
            borderRadius: 8,
            border: "1px solid rgba(255,255,255,0.2)",
            background: "rgba(255,255,255,0.08)",
            color: "var(--text)",
          }}
        />

        {error && <p style={{ color: "#ff8080", fontSize: "0.85rem", marginTop: -8, marginBottom: 12 }}>{error}</p>}

        <button
          type="submit"
          disabled={busy}
          style={{
            width: "100%",
            padding: "10px 0",
            borderRadius: "12px",
            background: "rgba(255,255,255,0.12)",
            border: "1px solid rgba(255,255,255,0.25)",
            color: "var(--text)",
            cursor: busy ? "default" : "pointer",
            opacity: busy ? 0.6 : 1,
          }}
        >
          {busy ? "Logger inn..." : "Logg inn"}
        </button>
      </form>
    </WindowChrome>
  );
}
