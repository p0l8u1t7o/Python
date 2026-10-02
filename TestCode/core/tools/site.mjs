// 展示首頁：本機伺服器與 GitHub Pages 建置共用同一份產生器。
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

export function galleryHtml(projects, { catalog = true } = {}) {
  const cards = projects.map(p => `<a href="./${encodeURIComponent(p.id)}/"><strong>${esc(p.title)}</strong>${p.summary ? `<em>${esc(p.summary)}</em>` : ''}<span>${esc(p.id)}</span></a>`).join('');
  const extra = catalog ? '<p class="more"><a class="link" href="./core/catalog/">共用 3D 模型目錄 →</a></p>' : '';
  return `<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>自動化設備 3D 展示</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101923;color:#eaf3fa;font-family:system-ui,sans-serif}
main{max-width:1040px;margin:auto;padding:64px 16px}h1{font-size:clamp(28px,5vw,42px)}p{color:#b1c5d6;line-height:1.8}
nav{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px;margin-top:32px}
nav a{display:flex;flex-direction:column;gap:12px;padding:28px;border:1px solid #3b5268;border-radius:14px;color:inherit;text-decoration:none;background:#1a2a3a}
nav a:hover,nav a:focus-visible{border-color:#6edbd4;background:#213a4c}strong{font-size:21px}
em{font-style:normal;color:#c9d9e6;font-size:14px;line-height:1.6}span{color:#9db8cd;font-size:13px;overflow-wrap:anywhere}
.more{margin-top:36px}.link{color:#6edbd4}
</style></head><body><main><h1>自動化設備 3D 展示</h1>
<p>選擇專案，探索設備動作、製程流程與模擬相機畫面。<br>本展示為工程模擬，檢測標記不代表實際量測結果。</p>
<nav>${cards}</nav>${extra}</main></body></html>`;
}
