import { useCallback, useEffect, useRef, useState } from 'react';
import { IxButton, IxCard, IxCardContent, IxContentHeader, IxMessageBar, IxPill, IxSpinner, IxTypography } from '@siemens/ix-react';
import { ModelViewer } from '../components/ModelViewer';

/** text-to-cad Studio：輸入描述 → Claude 產生 build123d 程式 → cadgen 建置 → 3D 預覽 → 匯出 STEP/GLB/STL/3MF */

interface Job {
  id: string; created_at: string; mode: string; prompt: string; name: string; parent_id: string | null;
  code: string; status: string; log: string; error: string; ai_notes: string;
  glb: string | null; step: string | null; stl: string | null; three_mf: string | null; snapshot: string | null;
  facts: Record<string, unknown>;
}
interface Env { cad_ok: boolean; cad_error: string | null; ai_ok: boolean; provider: string; model: string; ai_hint: string }
interface LibItem { name: string; signature: string; doc: string }

const STATUS_LABEL: Record<string, string> = { queued: '排隊中', generating: 'AI 產生程式中…', building: '建置 CAD 中…', done: '完成', failed: '失敗' };
const EXAMPLES = [
  'SMC MHZ2-25D 平行夾爪：本體 50×32×62 mm，兩指開閉行程 14 mm，底面 4 個 M5 安裝孔',
  'ISO 9409-1-63-4-M6 機械手臂法蘭：外徑 63、PCD 50、4×M6、中心定位凸台 Ø31.5 H7',
  '光電感測器 L 型安裝支架：2 mm 鈑金、底座 40×30 有兩個 Ø4.5 長孔、立板 30×40 有 Ø3.4 孔',
  '輸送帶擋停座：鋁塊 60×40×50，中央 Ø20 通孔裝氣缸，四角 M6 螺孔',
  'M12 A-code 4 pin 感測器接頭，含滾花螺帽與 40 mm 線纜',
];
const CODE_TEMPLATE = `from build123d import *
from cadgen import srgb
import parts  # 本專案零件庫（parts.pneumatic_cylinder、parts.gripper、parts.plc…）

# 單位 mm、+Z 向上、原點在底面中心
width = 60.0
depth = 40.0
height = 50.0
hole_d = 20.0


def gen_step():
    body = Box(width, depth, height, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body = fillet(body.edges().filter_by(Axis.Z), 4.0)
    bore = Pos(0, 0, -1) * Cylinder(hole_d / 2, height + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    screws = [Pos(sx * 22, sy * 12, -1) * Cylinder(2.5, height + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)) for sx in (-1, 1) for sy in (-1, 1)]
    part = body - ([bore] + screws)
    part.color = srgb("#C9CED3")
    part.label = "stopper_block"
    return part
`;

export default function CadStudioPage() {
  const [env, setEnv] = useState<Env | null>(null);
  const [lib, setLib] = useState<LibItem[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [mode, setMode] = useState<'ai' | 'code'>('ai');
  void mode;
  const [prompt, setPrompt] = useState('');
  const [code, setCode] = useState(CODE_TEMPLATE);
  const [name, setName] = useState('');
  const [current, setCurrent] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [attachTarget, setAttachTarget] = useState('');
  const pollRef = useRef<number | null>(null);

  const refreshJobs = useCallback(() => fetch('/api/cad/jobs').then((r) => r.json()).then(setJobs), []);

  useEffect(() => {
    fetch('/api/cad/env').then((r) => r.json()).then(setEnv);
    fetch('/api/cad/library').then((r) => r.json()).then(setLib);
    refreshJobs();
  }, [refreshJobs]);

  // 輪詢目前工作
  useEffect(() => {
    if (!current || current.status === 'done' || current.status === 'failed') { setBusy(false); return; }
    setBusy(true);
    pollRef.current = window.setInterval(async () => {
      const j: Job = await fetch(`/api/cad/jobs/${current.id}`).then((r) => r.json());
      setCurrent(j);
      if (j.status === 'done' || j.status === 'failed') { refreshJobs(); if (j.code) setCode(j.code); }
    }, 1500);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [current?.id, current?.status, refreshJobs]);

  const submit = async (revise = false, useMode: 'ai' | 'code' = mode) => {
    setMsg(null);
    const body = { mode: useMode, prompt, code: useMode === 'code' ? code : '', name, parent_id: revise && current ? current.id : null };
    const r = await fetch('/api/cad/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) { setMsg(`送出失敗：${(await r.json()).message ?? r.statusText}`); return; }
    setCurrent(await r.json());
  };

  const exportFmt = async (fmt: 'stl' | '3mf') => {
    if (!current) return;
    setBusy(true);
    const j: Job = await fetch(`/api/cad/jobs/${current.id}/export`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format: fmt }) }).then((r) => r.json());
    setCurrent(j); setBusy(false);
  };

  const attach = async () => {
    if (!current || !attachTarget) return;
    const kind = attachTarget.includes('/') ? 'component' : 'equipment';
    const res = await fetch(`/api/cad/jobs/${current.id}/attach`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, target: attachTarget }) }).then((r) => r.json());
    setMsg(res.ok ? `已掛到 ${res.name}（${res.attached}）` : `掛載失敗：${res.error ?? ''}`);
  };

  const load = (j: Job) => { setCurrent(j); if (j.code) setCode(j.code); if (j.prompt) setPrompt(j.prompt); setName(j.name); };

  const facts = current?.facts ?? {};
  const bounds = facts.bounds as { min: number[]; max: number[] } | undefined;

  return (
    <div className="page">
      <IxContentHeader headerTitle="CAD Studio（text-to-cad）" headerSubtitle="用文字描述零件，由 AI 寫出 build123d 參數化程式並建置成真正的 CAD；可預覽、修改程式、匯出 STEP / GLB / STL / 3MF，或直接掛到某個元件。" />

      {env && !env.cad_ok && <IxMessageBar type="alarm">{env.cad_error}</IxMessageBar>}
      {env && env.cad_ok && !env.ai_ok && (
        <IxMessageBar type="warning">
          尚未設定 {env.provider} 的 API 金鑰，「AI 產碼」模式無法使用（「直接執行程式」與零件庫不受影響）。設定方式：在專案根目錄把 .env.example 複製成 .env，{env.ai_hint}，再執行 .\stop.ps1 與 .\start.ps1。
        </IxMessageBar>
      )}
      {msg && <IxMessageBar type="info" onClosedChange={() => setMsg(null)}>{msg}</IxMessageBar>}

      <div className="studio-layout">
        {/* 左：輸入 */}
        <div>
          <IxCard>
            <IxCardContent>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem' }}>
                <IxTypography format="h5">1. 描述零件 → 按「AI 產生 3D CAD」</IxTypography>
                {env && <IxTypography format="label-sm" textColor="soft">{env.provider} · {env.model}</IxTypography>}
              </div>
              <input className="studio-input" placeholder="名稱（選填，例如：夾爪 MHZ2-25D）" value={name} onChange={(e) => setName(e.target.value)} />
              <textarea className="studio-textarea" rows={5} placeholder="描述零件：類型、品牌型號、用途、關鍵尺寸（mm）、孔位、安裝方式…（例：DENSO HSR-048 四軸 SCARA，臂長 480 mm）" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
              <div className="studio-examples">
                {EXAMPLES.map((ex) => (
                  <button key={ex} type="button" className="studio-example" onClick={() => setPrompt(ex)}>{ex.slice(0, 28)}…</button>
                ))}
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center', margin: '0.25rem 0 0.75rem' }}>
                <IxButton variant="primary" disabled={busy || !prompt.trim() || (env ? !env.ai_ok : false)} onClick={() => { setMode('ai'); submit(false, 'ai'); }}>
                  AI 產生 3D CAD
                </IxButton>
                {current && current.mode === 'ai' && (current.status === 'done' || current.status === 'failed') && (
                  <IxButton variant="secondary" disabled={busy || !prompt.trim()} onClick={() => { setMode('ai'); submit(true, 'ai'); }}>依上一版修訂</IxButton>
                )}
                {env && !env.ai_ok && <IxTypography format="label-sm" textColor="soft">（需先設定 API 金鑰）</IxTypography>}
              </div>
              <div className="section-title">2.（進階）build123d 程式：AI 產生後會出現在這裡；可自行修改後按「執行下方程式」</div>
              <textarea className="studio-code" rows={16} spellCheck={false} value={code} onChange={(e) => setCode(e.target.value)} />
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center', marginTop: '0.5rem' }}>
                <select className="studio-input" style={{ width: 260 }} defaultValue="" onChange={(e) => { const it = lib.find((l) => l.name === e.target.value); if (it) { setCode(`import parts\nfrom build123d import *\n\n\ndef gen_step():\n    # ${it.doc}\n    return ${it.signature}\n`); } e.target.value = ''; }}>
                  <option value="">從零件庫插入範本（93 個 builder）…</option>
                  {lib.map((l) => <option key={l.name} value={l.name}>{l.name} — {l.doc.slice(0, 30)}</option>)}
                </select>
                <IxButton variant="secondary" disabled={busy || !code.includes('gen_step')} onClick={() => { setMode('code'); submit(false, 'code'); }}>
                  執行下方程式
                </IxButton>
              </div>
            </IxCardContent>
          </IxCard>

          <IxCard style={{ marginTop: '0.75rem' }}>
            <IxCardContent>
              <IxTypography format="h5">最近的工作</IxTypography>
              <div className="studio-jobs">
                {jobs.map((j) => (
                  <div key={j.id} className={`studio-job ${current?.id === j.id ? 'active' : ''}`} onClick={() => load(j)}>
                    {j.snapshot ? <img src={j.snapshot} alt="" /> : <div className="ph" />}
                    <div>
                      <div className="title">{j.name || j.prompt.slice(0, 40) || '(程式模式)'}</div>
                      <div className="sub">{new Date(j.created_at).toLocaleString()} · {STATUS_LABEL[j.status] ?? j.status}</div>
                    </div>
                  </div>
                ))}
                {jobs.length === 0 && <IxTypography format="body-sm" textColor="soft">尚無工作</IxTypography>}
              </div>
            </IxCardContent>
          </IxCard>
        </div>

        {/* 右：結果 */}
        <div>
          <IxCard>
            <IxCardContent>
              {!current && <IxTypography format="body-sm" textColor="soft">左側輸入描述或程式後，3D 結果會顯示在這裡。</IxTypography>}
              {current && (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <IxPill variant={current.status === 'done' ? 'success' : current.status === 'failed' ? 'alarm' : 'info'}>{STATUS_LABEL[current.status] ?? current.status}</IxPill>
                    {busy && <IxSpinner size="small" />}
                    <IxTypography format="body-sm" textColor="soft">{current.name || current.prompt.slice(0, 60)}</IxTypography>
                  </div>
                  {current.status === 'done' && current.glb && (
                    <div className="studio-viewer"><ModelViewer url={current.glb} /></div>
                  )}
                  {current.status === 'done' && (
                    <>
                      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
                        {current.step && <a className="studio-dl" href={current.step} download>下載 STEP</a>}
                        {current.glb && <a className="studio-dl" href={current.glb} download>下載 GLB</a>}
                        {current.stl ? <a className="studio-dl" href={current.stl} download>下載 STL</a> : <IxButton variant="subtle-secondary" disabled={busy} onClick={() => exportFmt('stl')}>匯出 STL</IxButton>}
                        {current.three_mf ? <a className="studio-dl" href={current.three_mf} download>下載 3MF</a> : <IxButton variant="subtle-secondary" disabled={busy} onClick={() => exportFmt('3mf')}>匯出 3MF</IxButton>}
                        {current.snapshot && <a className="studio-dl" href={current.snapshot} target="_blank" rel="noreferrer">快照 PNG</a>}
                      </div>
                      {bounds && (
                        <IxTypography format="body-sm" textColor="soft" style={{ marginTop: '0.5rem' }}>
                          邊界 {(bounds.max[0] - bounds.min[0]).toFixed(1)} × {(bounds.max[1] - bounds.min[1]).toFixed(1)} × {(bounds.max[2] - bounds.min[2]).toFixed(1)} mm · 面 {String(facts.faceCount ?? '-')} · 邊 {String(facts.edgeCount ?? '-')} · {String(facts.kind ?? '')}
                        </IxTypography>
                      )}
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '0.75rem' }}>
                        <input className="studio-input" style={{ flex: 1 }} placeholder="掛到元件：<設備slug>/<元件slug>（例 aoi/camera）或整台設備 slug" value={attachTarget} onChange={(e) => setAttachTarget(e.target.value)} />
                        <IxButton variant="secondary" disabled={!attachTarget} onClick={attach}>掛到教育訓練頁</IxButton>
                      </div>
                    </>
                  )}
                  {current.ai_notes && (
                    <>
                      <div className="section-title">AI 說明與假設</div>
                      <pre className="studio-notes">{current.ai_notes}</pre>
                    </>
                  )}
                  {current.status === 'failed' && (
                    <>
                      <div className="section-title">錯誤</div>
                      <pre className="studio-log error">{current.error}</pre>
                      {current.mode === 'ai' && <IxTypography format="body-sm" textColor="soft">按「依上一版修訂」讓 AI 根據錯誤訊息修正，或自行修改程式後用「直接執行程式」。</IxTypography>}
                    </>
                  )}
                  {current.log && (
                    <details style={{ marginTop: '0.5rem' }}>
                      <summary style={{ cursor: 'pointer', fontSize: '0.8rem' }}>建置記錄</summary>
                      <pre className="studio-log">{current.log}</pre>
                    </details>
                  )}
                </>
              )}
            </IxCardContent>
          </IxCard>
        </div>
      </div>
    </div>
  );
}
