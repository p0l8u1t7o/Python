import { useEffect, useState, type ReactNode } from "react";
import type { Judgment, QualityLevel } from "../api/types";
import { useApp } from "../app/context";

export function JudgmentBadge({ value }: { value: Judgment | string }) {
  const { t } = useApp();
  return <span className={`badge j-${value}`}>{t(`judgment.${value}`)}</span>;
}

export function QualityBadge({ value }: { value: QualityLevel | string }) {
  const { t } = useApp();
  return <span className={`badge q-${value}`}>{t(`quality.${value}`)}</span>;
}

export function StatusText({ prefix, value }: { prefix: string; value: string }) {
  const { t } = useApp();
  return <span>{t(`${prefix}.${value}`)}</span>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const { errorText } = useApp();
  if (!error) return null;
  return <div className="alert error">{errorText(error)}</div>;
}

export function Card({ title, actions, children, bodyClass = "card-b" }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; bodyClass?: string }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-h">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {actions}
        </div>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function Empty({ children }: { children?: ReactNode }) {
  const { t } = useApp();
  return <div className="empty">{children ?? t("ui.empty")}</div>;
}

export function Modal({ title, onClose, children, footer }:
  { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card modal" role="dialog" aria-label={title}>
        <div className="card-h"><h2>{title}</h2></div>
        <div className="card-b stack">{children}</div>
        {footer && <div className="card-b row" style={{ justifyContent: "flex-end", borderTop: "1px solid var(--border)" }}>{footer}</div>}
      </div>
    </div>
  );
}

export function fmt(v: unknown, digits = 2): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "number") return Number.isInteger(v) && digits > 0 && Math.abs(v) > 1000 ? v.toLocaleString() : v.toFixed(digits);
  return String(v);
}

export function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "–";
  return (v >= 0 ? "+" : "") + v.toFixed(digits);
}

// 本地日期 YYYY-MM-DD (與後端的本地時間一致)
export function localDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// 本地時間 YYYY-MM-DD HH:MM:SS
export function localNow(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${localDay(d)} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function fmtTime(s: string | null | undefined): string {
  return s ? s.replace("T", " ") : "–";
}

// 以 promise 載入資料的簡易 hook
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): [T | null, unknown, () => void, boolean] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => {
        if (alive) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return [data, error, () => setN((x) => x + 1), loading];
}
