import { useState, type ReactNode } from "react";
import { send } from "../api/client";
import type { Locale } from "../api/types";
import { useApp } from "../app/context";
import { ErrorBox } from "../components/ui";

// 未登入、首次設定、需變更密碼時顯示對應畫面，否則顯示應用程式
export function AuthGate({ children }: { children: ReactNode }) {
  const { auth } = useApp();
  if (!auth) return <Centered><div className="muted">…</div></Centered>;
  if (auth.setup_required) return <Setup />;
  if (!auth.user) return <Login />;
  if (auth.user.must_change_password) return <ChangePassword forced />;
  return <>{children}</>;
}

function Centered({ children }: { children: ReactNode }) {
  const { t, locale, setLocale } = useApp();
  return (
    <div style={{ minHeight: "100%", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ width: 380 }} className="stack">
        <div style={{ textAlign: "center" }}>
          <div className="brand-name" style={{ fontSize: 24 }}>{t("product.name")}</div>
          <div className="muted">{t("product.tagline")}</div>
        </div>
        {children}
        <div style={{ textAlign: "center" }}>
          <select aria-label={t("ui.language")} value={locale} onChange={(e) => setLocale(e.target.value as Locale)}>
            <option value="zh-TW">繁體中文</option>
            <option value="en">English</option>
          </select>
        </div>
      </div>
    </div>
  );
}

function Login() {
  const { t, refreshAuth } = useApp();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await send("POST", "/api/auth/login", { username, password });
      setError(null);
      refreshAuth();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Centered>
      <form className="card card-b stack" onSubmit={submit}>
        <h2>{t("ui.auth.login")}</h2>
        <label className="field">{t("ui.auth.username")}<input type="text" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} /></label>
        <label className="field">{t("ui.auth.password")}<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <ErrorBox error={error} />
        <button className="btn primary" type="submit" disabled={busy || !username || !password}>{t("ui.auth.login")}</button>
      </form>
    </Centered>
  );
}

function Setup() {
  const { t, refreshAuth } = useApp();
  const [username, setUsername] = useState("admin");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const mismatch = confirm.length > 0 && confirm !== password;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await send("POST", "/api/auth/setup", { username, display_name: displayName, password });
      refreshAuth();
    } catch (err) {
      setError(err);
    }
  };
  return (
    <Centered>
      <form className="card card-b stack" onSubmit={submit}>
        <h2>{t("ui.auth.setup")}</h2>
        <div className="muted">{t("ui.auth.setup_hint")}</div>
        <label className="field">{t("ui.auth.username")}<input type="text" value={username} onChange={(e) => setUsername(e.target.value)} /></label>
        <label className="field">{t("ui.auth.display_name")}<input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></label>
        <label className="field">{t("ui.auth.password")}<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <span className="hint">{t("ui.auth.password_rule")}</span></label>
        <label className="field">{t("ui.auth.password_confirm")}<input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>
        {mismatch && <div className="alert error">{t("ui.auth.password_mismatch")}</div>}
        <ErrorBox error={error} />
        <button className="btn primary" type="submit" disabled={!username || !password || mismatch || confirm !== password}>{t("ui.auth.create_admin")}</button>
      </form>
    </Centered>
  );
}

export function ChangePassword({ forced, onDone }: { forced?: boolean; onDone?: () => void }) {
  const { t, refreshAuth } = useApp();
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const mismatch = confirm.length > 0 && confirm !== newPw;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await send("POST", "/api/auth/password", { old_password: oldPw, new_password: newPw });
      refreshAuth();
      onDone?.();
    } catch (err) {
      setError(err);
    }
  };
  const form = (
    <form className="card card-b stack" onSubmit={submit}>
      <h2>{t("ui.auth.change_password")}</h2>
      {forced && <div className="muted">{t("ui.auth.must_change_hint")}</div>}
      <label className="field">{t("ui.auth.old_password")}<input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} /></label>
      <label className="field">{t("ui.auth.new_password")}<input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
        <span className="hint">{t("ui.auth.password_rule")}</span></label>
      <label className="field">{t("ui.auth.password_confirm")}<input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>
      {mismatch && <div className="alert error">{t("ui.auth.password_mismatch")}</div>}
      <ErrorBox error={error} />
      <div className="row">
        {forced && <button type="button" className="btn" onClick={() => send("POST", "/api/auth/logout").then(refreshAuth)}>{t("ui.auth.logout")}</button>}
        <span className="spacer" />
        <button className="btn primary" type="submit" disabled={!oldPw || !newPw || confirm !== newPw}>{t("ui.save")}</button>
      </div>
    </form>
  );
  return forced ? <Centered>{form}</Centered> : form;
}
