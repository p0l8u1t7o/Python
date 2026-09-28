import { useState } from "react";

export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  danger = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const confirm = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await onConfirm();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" onClick={(event) => event.stopPropagation()}>
      <div className="modal" role="alertdialog" aria-label={title}>
        <h2>{title}</h2>
        <p className="confirm-message">{message}</p>
        {error && <p className="confirm-error">{error}</p>}
        <div>
          <button onClick={onCancel} disabled={busy}>
            取消
          </button>
          <button
            className={danger ? "danger" : "primary"}
            onClick={() => void confirm()}
            disabled={busy}
          >
            {busy ? "處理中…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
