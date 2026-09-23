import { useState } from "react";
import { get, send } from "../api/client";
import type { Role, User } from "../api/types";
import { useApp } from "../app/context";
import { Layout } from "../components/Layout";
import { Card, ErrorBox, Modal, fmtTime, useLoad } from "../components/ui";

const ROLES: Role[] = ["operator", "engineer", "admin"];

export function Users() {
  const { t, auth } = useApp();
  const [users, error, reload] = useLoad(() => get<User[]>("/api/users"), []);
  const [err, setErr] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<User | null>(null);

  const patch = async (u: User, body: Partial<Pick<User, "role" | "active">>) => {
    try {
      await send("PATCH", `/api/users/${u.id}`, body);
      setErr(null);
      reload();
    } catch (e) {
      setErr(e);
    }
  };

  return (
    <Layout title={t("ui.nav.users")} actions={<button className="btn primary" onClick={() => setCreating(true)}>{t("ui.users.new")}</button>}>
      <div className="stack">
        <div className="alert info">{t("ui.users.hint")}</div>
        <ErrorBox error={error || err} />
        <Card bodyClass="">
          <table className="table">
            <thead><tr><th>{t("ui.auth.username")}</th><th>{t("ui.auth.display_name")}</th><th>{t("ui.users.role")}</th>
              <th>{t("ui.status")}</th><th>{t("ui.users.last_login")}</th><th></th></tr></thead>
            <tbody>
              {users?.map((u) => (
                <tr key={u.id}>
                  <td className="mono">{u.username}</td>
                  <td>{u.display_name}</td>
                  <td>
                    <select value={u.role} disabled={u.id === auth?.user?.id} onChange={(e) => patch(u, { role: e.target.value as Role })}>
                      {ROLES.map((r) => <option key={r} value={r}>{t(`role.${r}`)}</option>)}
                    </select>
                  </td>
                  <td>
                    {u.active ? t("ui.enabled") : t("ui.disabled")}
                    {u.locked && <span className="badge q-warn" style={{ marginLeft: 6 }}>{t("ui.users.locked")}</span>}
                    {u.must_change_password && <span className="muted" style={{ marginLeft: 6, fontSize: "var(--fs-xs)" }}>{t("ui.users.must_change")}</span>}
                  </td>
                  <td>{fmtTime(u.last_login_at)}</td>
                  <td>
                    <div className="row" style={{ justifyContent: "flex-end" }}>
                      <button className="btn small" onClick={() => setResetting(u)}>{t("ui.users.reset_password")}</button>
                      {u.id !== auth?.user?.id && (
                        <button className="btn small" onClick={() => patch(u, { active: !u.active })}>{u.active ? t("ui.users.deactivate") : t("ui.users.activate")}</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      {creating && <CreateUser onClose={() => setCreating(false)} onDone={() => { setCreating(false); reload(); }} />}
      {resetting && <ResetPassword user={resetting} onClose={() => setResetting(null)} />}
    </Layout>
  );
}

function CreateUser({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useApp();
  const [f, setF] = useState({ username: "", display_name: "", role: "operator" as Role, password: "" });
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal title={t("ui.users.new")} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>{t("ui.cancel")}</button>
        <button className="btn primary" disabled={!f.username || !f.password} onClick={async () => {
          try {
            await send("POST", "/api/users", f);
            onDone();
          } catch (e) {
            setError(e);
          }
        }}>{t("ui.add")}</button></>}>
      <label className="field">{t("ui.auth.username")}<input type="text" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></label>
      <label className="field">{t("ui.auth.display_name")}<input type="text" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></label>
      <label className="field">{t("ui.users.role")}
        <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
          {ROLES.map((r) => <option key={r} value={r}>{t(`role.${r}`)}</option>)}
        </select>
        <span className="hint">{t(`ui.users.role_hint.${f.role}`)}</span>
      </label>
      <label className="field">{t("ui.users.initial_password")}<input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <span className="hint">{t("ui.users.initial_password_hint")}</span></label>
      <ErrorBox error={error} />
    </Modal>
  );
}

function ResetPassword({ user, onClose }: { user: User; onClose: () => void }) {
  const { t } = useApp();
  const [pw, setPw] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  return (
    <Modal title={`${t("ui.users.reset_password")}：${user.username}`} onClose={onClose}
      footer={done ? <button className="btn primary" onClick={onClose}>{t("ui.close")}</button> : <>
        <button className="btn" onClick={onClose}>{t("ui.cancel")}</button>
        <button className="btn primary" disabled={!pw} onClick={async () => {
          try {
            await send("POST", `/api/users/${user.id}/reset-password`, { new_password: pw });
            setDone(true);
          } catch (e) {
            setError(e);
          }
        }}>{t("ui.confirm")}</button></>}>
      {done ? <div className="alert info">{t("ui.users.reset_done")}</div> : <>
        <label className="field">{t("ui.auth.new_password")}<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
          <span className="hint">{t("ui.users.initial_password_hint")}</span></label>
        <ErrorBox error={error} />
      </>}
    </Modal>
  );
}
