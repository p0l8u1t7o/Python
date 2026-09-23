import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { send } from "../api/client";
import type { Locale } from "../api/types";
import { useApp, type ThemeMode } from "../app/context";
import { ChangePassword } from "../pages/Auth";
import { Modal } from "./ui";

// 導覽項目與所需權限 (後端仍會逐一檢查)
const NAV: { section: string; items: { to: string; key: string; perm: string }[] }[] = [
  {
    section: "ui.nav.section.inspection",
    items: [
      { to: "/", key: "ui.nav.overview", perm: "view" },
      { to: "/runs", key: "ui.nav.runs", perm: "view" },
      { to: "/imports", key: "ui.nav.imports", perm: "import" },
    ],
  },
  {
    section: "ui.nav.section.engineering",
    items: [
      { to: "/recipes", key: "ui.nav.recipes", perm: "view" },
      { to: "/watch", key: "ui.nav.watch", perm: "view" },
      { to: "/diagnostics", key: "ui.nav.diagnostics", perm: "diagnostics" },
    ],
  },
  {
    section: "ui.nav.section.system",
    items: [
      { to: "/audit", key: "ui.nav.audit", perm: "audit_view" },
      { to: "/users", key: "ui.nav.users", perm: "user_manage" },
      { to: "/system", key: "ui.nav.system", perm: "settings" },
    ],
  },
];

export function Layout({ title, actions, full, children }:
  { title: string; actions?: ReactNode; full?: boolean; children: ReactNode }) {
  const { t, system, locale, setLocale, theme, setTheme, auth, can, refreshAuth } = useApp();
  const [menu, setMenu] = useState(false);
  const [pw, setPw] = useState(false);
  const user = auth?.user;
  return (
    <div className="app">
      <aside className="sidebar no-print">
        <div className="brand">
          <div className="brand-name">{t("product.name")}</div>
          <div className="brand-sub">{t("product.tagline")}</div>
        </div>
        <nav className="nav">
          {NAV.map((g) => {
            const items = g.items.filter((i) => can(i.perm));
            if (!items.length) return null;
            return (
              <div key={g.section}>
                <div className="nav-section">{t(g.section)}</div>
                {items.map((i) => <NavLink key={i.to} to={i.to} end={i.to === "/"}>{t(i.key)}</NavLink>)}
              </div>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <div>{t("ui.version")} {system?.version ?? "–"}</div>
          {system && Object.entries(system.modules).map(([k, v]) => <div key={k}>{t(`module.${k}`)} {v}</div>)}
        </div>
      </aside>
      <main className="main">
        <header className="topbar no-print">
          <h1>{title}</h1>
          {actions}
          <select aria-label={t("ui.language")} value={locale} onChange={(e) => setLocale(e.target.value as Locale)}>
            <option value="zh-TW">繁體中文</option>
            <option value="en">English</option>
          </select>
          <select aria-label={t("ui.theme")} value={theme} onChange={(e) => setTheme(e.target.value as ThemeMode)}>
            <option value="system">{t("ui.theme.system")}</option>
            <option value="light">{t("ui.theme.light")}</option>
            <option value="dark">{t("ui.theme.dark")}</option>
          </select>
          {user && (
            <div style={{ position: "relative" }}>
              <button className="btn" onClick={() => setMenu(!menu)} aria-haspopup="menu">
                {user.display_name} <span className="muted">· {t(`role.${user.role}`)}</span>
              </button>
              {menu && (
                <div className="card" role="menu" style={{ position: "absolute", right: 0, top: 38, zIndex: 20, minWidth: 180, padding: 6 }}
                  onMouseLeave={() => setMenu(false)}>
                  <div className="muted" style={{ padding: "4px 8px", fontSize: "var(--fs-xs)" }}>{user.username}</div>
                  <button className="btn ghost" style={{ width: "100%" }} onClick={() => { setMenu(false); setPw(true); }}>{t("ui.auth.change_password")}</button>
                  <button className="btn ghost" style={{ width: "100%" }}
                    onClick={() => send("POST", "/api/auth/logout").finally(refreshAuth)}>{t("ui.auth.logout")}</button>
                </div>
              )}
            </div>
          )}
        </header>
        <Banners />
        <div className={full ? "content full" : "content"}>{children}</div>
      </main>
      {pw && (
        <Modal title={t("ui.auth.change_password")} onClose={() => setPw(false)}>
          <ChangePassword onDone={() => setPw(false)} />
        </Modal>
      )}
    </div>
  );
}

// 授權到期／無效、磁碟空間不足的提示 (所有登入者可見)
function Banners() {
  const { t, auth, system } = useApp();
  const lic = auth?.license;
  const out: { cls: string; text: string }[] = [];
  if (lic && lic.enforced && !lic.analysis_allowed) {
    out.push({ cls: "error", text: `${t(`license.${lic.state}`)}：${t("ui.banner.analysis_stopped")}` });
  } else if (lic && lic.enforced && lic.state === "grace") {
    out.push({ cls: "error", text: t("ui.banner.grace") });
  } else if (lic && lic.enforced && lic.warn && lic.days_left !== undefined) {
    out.push({ cls: "info", text: t("ui.banner.expiring").replace("{n}", String(lic.days_left)) });
  }
  if (system?.disk?.low) out.push({ cls: "error", text: t("ui.banner.disk_low").replace("{n}", String(system.disk.free_gb)) });
  if (!out.length) return null;
  return (
    <div className="no-print" style={{ padding: "var(--sp-2) var(--sp-5) 0" }}>
      {out.map((b, i) => <div key={i} className={`alert ${b.cls}`} style={{ marginBottom: 6 }}>{b.text}</div>)}
    </div>
  );
}
