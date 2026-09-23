import { useState } from "react";
import { send } from "../api/client";
import { useApp } from "../app/context";
import { ErrorBox, Modal } from "./ui";

interface ExportResult {
  name: string;
  sha256: string;
  size: number;
  parts: string[];
}

// 問題回報包匯出 (規劃書第 13 節)
export function DiagnosticsDialog({ runIds, onClose }: { runIds: number[]; onClose: () => void }) {
  const { t } = useApp();
  const [description, setDescription] = useState("");
  const [includeImages, setIncludeImages] = useState(true);
  const [deidentify, setDeidentify] = useState(false);
  const [encrypt, setEncrypt] = useState(false);
  const [splitMb, setSplitMb] = useState(2048);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<ExportResult | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setDone(await send<ExportResult>("POST", "/api/diagnostics", {
        run_ids: runIds, description, include_images: includeImages, deidentify, encrypt, split_mb: splitMb,
      }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={t("ui.diag.title")} onClose={onClose}
      footer={done ? <button className="btn primary" onClick={onClose}>{t("ui.close")}</button> : <>
        <button className="btn" onClick={onClose}>{t("ui.cancel")}</button>
        <button className="btn primary" disabled={busy || !runIds.length} onClick={run}>{busy ? t("ui.working") : t("ui.diag.export")}</button>
      </>}>
      {done ? (
        <div className="stack">
          <div className="alert info">{t("ui.diag.done")}</div>
          {done.parts.map((p) => <a key={p} className="mono" href={`/api/diagnostics/files/${encodeURIComponent(p)}`}>{p}</a>)}
          <div className="muted mono" style={{ fontSize: "var(--fs-xs)" }}>SHA-256 {done.sha256}</div>
        </div>
      ) : (
        <>
          <div className="muted">{t("ui.diag.selected").replace("{n}", String(runIds.length))}</div>
          <label className="field">{t("ui.diag.description")}
            <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t("ui.diag.description_hint")} />
          </label>
          <label className="check"><input type="checkbox" checked={includeImages} onChange={(e) => setIncludeImages(e.target.checked)} />{t("ui.diag.include_images")}</label>
          <label className="check"><input type="checkbox" checked={deidentify} onChange={(e) => setDeidentify(e.target.checked)} />{t("ui.diag.deidentify")}</label>
          <label className="check"><input type="checkbox" checked={encrypt} onChange={(e) => setEncrypt(e.target.checked)} />{t("ui.diag.encrypt")}</label>
          <label className="field">{t("ui.diag.split")}
            <input type="number" min={10} value={splitMb} onChange={(e) => setSplitMb(Number(e.target.value) || 2048)} />
          </label>
          <ErrorBox error={error} />
        </>
      )}
    </Modal>
  );
}
