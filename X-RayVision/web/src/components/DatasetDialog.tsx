import { useState } from "react";
import { ApiError } from "../api/client";
import { useApp } from "../app/context";
import { ErrorBox, Modal } from "./ui";

// 訓練資料匯出：已標註影像的焊點裁切＋遮罩＋dataset.json (單一 ZIP)
export function DatasetDialog({ runIds, onClose }: { runIds: number[]; onClose: () => void }) {
  const { t } = useApp();
  const [deid, setDeid] = useState(false);
  const [withImages, setWithImages] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch("/api/annotations/export", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_ids: runIds, deidentify: deid, module_id: "void", include_images: withImages }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.error || `http_${res.status}`, b.detail || "");
      }
      const name = (res.headers.get("content-disposition") || "").split("filename=")[1] || "dataset.zip";
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={t("ui.annot.export")} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>{t("ui.cancel")}</button>
        <button className="btn primary" disabled={busy} onClick={run}>{t("ui.confirm")}</button></>}>
      <div className="stack">
        <p>{t("ui.diag.selected").replace("{n}", String(runIds.length))}</p>
        <p className="muted">{t("ui.annot.export_hint")}</p>
        <label className="check"><input type="checkbox" checked={deid} onChange={(e) => setDeid(e.target.checked)} />{t("ui.diag.deidentify")}</label>
        <label className="check"><input type="checkbox" checked={withImages} onChange={(e) => setWithImages(e.target.checked)} />{t("ui.annot.with_images")}</label>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}
