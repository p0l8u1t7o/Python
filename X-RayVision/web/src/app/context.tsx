import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, get, setUnauthorizedHandler } from "../api/client";
import type { AuthState, Labels, Locale, ModuleInfo, SystemInfo } from "../api/types";

// ---------------------------------------------------------------------------
// 偏好設定 (僅存於本機瀏覽器)
// ---------------------------------------------------------------------------
function load(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 忽略 */
  }
}

export type ThemeMode = "system" | "light" | "dark";

interface AppState {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, fallback?: string) => string;
  label: (l: Labels | undefined, fallback?: string) => string;
  errorText: (e: unknown) => string;
  theme: ThemeMode;
  setTheme: (m: ThemeMode) => void;
  system: SystemInfo | null;
  modules: Record<string, ModuleInfo>;
  refreshSystem: () => void;
  auth: AuthState | null;
  refreshAuth: () => void;
  can: (perm: string) => boolean;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(load("xrv.locale", "zh-TW") as Locale);
  const [catalog, setCatalog] = useState<Record<string, string>>({});
  const [theme, setThemeState] = useState<ThemeMode>(load("xrv.theme", "system") as ThemeMode);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [modules, setModules] = useState<Record<string, ModuleInfo>>({});
  const [auth, setAuth] = useState<AuthState | null>(null);

  const refreshAuth = useCallback(() => {
    get<AuthState>("/api/auth/state").then(setAuth).catch(() => setAuth(null));
  }, []);
  useEffect(() => {
    setUnauthorizedHandler(refreshAuth);
    refreshAuth();
  }, [refreshAuth]);

  // 語系：文字統一由後端語系檔提供 (產品文字單一來源)
  useEffect(() => {
    get<Record<string, string>>(`/api/i18n/${locale}`).then(setCatalog).catch(() => setCatalog({}));
    document.documentElement.lang = locale === "zh-TW" ? "zh-Hant" : "en";
  }, [locale]);

  // 主題：system 跟隨作業系統
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && mq.matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [theme]);

  const loggedIn = !!auth?.user && (auth?.permissions.length ?? 0) > 0;
  const refreshSystem = useCallback(() => {
    if (!loggedIn) return;
    get<SystemInfo>("/api/system").then(setSystem).catch(() => undefined);
    get<ModuleInfo[]>("/api/modules")
      .then((ms) => setModules(Object.fromEntries(ms.map((m) => [m.module_id, m]))))
      .catch(() => undefined);
  }, [loggedIn]);
  useEffect(refreshSystem, [refreshSystem]);

  const value = useMemo<AppState>(() => {
    const t = (key: string, fallback?: string) => catalog[key] ?? fallback ?? key;
    return {
      locale,
      setLocale: (l) => {
        save("xrv.locale", l);
        setLocaleState(l);
      },
      t,
      label: (l, fallback = "") => (l && (l[locale] || l["zh-TW"] || l["en"])) || fallback,
      errorText: (e) => {
        if (e instanceof ApiError) {
          const msg = catalog[`error.${e.code}`] ?? e.code;
          return e.detail ? `${msg}（${e.detail}）` : msg;
        }
        return catalog["ui.error.network"] ?? String(e);
      },
      theme,
      setTheme: (m) => {
        save("xrv.theme", m);
        setThemeState(m);
      },
      system,
      modules,
      refreshSystem,
      auth,
      refreshAuth,
      can: (perm) => !!auth?.permissions.includes(perm),
    };
  }, [catalog, locale, theme, system, modules, refreshSystem, auth, refreshAuth]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("AppProvider missing");
  return v;
}

// 原因代碼 (可能含 "模組.代碼:對象" 或 "代碼:對象") 轉為顯示文字
export function reasonText(t: AppState["t"], code: string): string {
  const [head, target] = code.split(":");
  const parts = head.split(".");
  const key = parts[parts.length - 1];
  const text = t(`reason.${key}`, t(`reject.${key}`, t(`note.${key}`, key)));
  if (!target) return text;
  const m = target.match(/^group(\d+)$/);
  const b = target.match(/^ball(\d+)$/);
  const where = m ? `${t("ui.group")} ${m[1]}` : b ? `${t("ui.ball")} ${b[1]}` : target === "image" ? t("ui.whole_image") : target;
  return `${text}（${where}）`;
}

// 定時重新整理
export function usePolling(fn: () => void, ms: number, deps: unknown[] = []) {
  useEffect(() => {
    fn();
    const h = window.setInterval(fn, ms);
    return () => window.clearInterval(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
