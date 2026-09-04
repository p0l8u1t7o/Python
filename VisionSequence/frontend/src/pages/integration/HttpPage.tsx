/** 整合 ▸ HTTP API：試打 `POST /flows/{id}/run`，並產生 curl／Python／C# 片段。 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Send } from 'lucide-react'

import { CodeBlock, CopyButton, useSectionInfo } from './shared'
import { TraceLog } from '@/components/integration/TraceLog'
import { Badge, Button, Card, CardBody, CardHeader, Checkbox, LoadingState, Select, Tabs, TextArea, TextInput } from '@/components/ui'
import { BASE_URL, apiKey, authToken, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useFlows } from '@/lib/queries'
import { isImageRef, type IntegrationInfo } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

// 分頁 1：HTTP API 測試
// ---------------------------------------------------------------------------
function snippets(base: string, flowId: string, mode: 'json' | 'file', context: string, wait: boolean, timeout: string, images: boolean, keyPlaceholder: string, recipe = '') {
  const qs = `wait=${wait ? 1 : 0}${wait && timeout ? `&timeout=${timeout}` : ''}${images ? '&include_images=1' : ''}`
  const url = `${base}/vision/flows/${flowId || '{id}'}/run?${qs}`
  const ctx = context.trim() || '{}'
  const recipeJson = recipe ? `, "recipe": ${JSON.stringify(recipe)}` : ''
  const recipeForm = recipe ? ` \\\n  -F 'recipe=${recipe}'` : ''
  const curl = mode === 'json'
    ? `curl -X POST "${url}" \\\n  -H "X-API-Key: ${keyPlaceholder}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"context": ${ctx}${recipeJson}}'`
    : `curl -X POST "${url}" \\\n  -H "X-API-Key: ${keyPlaceholder}" \\\n  -F "image=@part.png" \\\n  -F 'context=${ctx}'${recipeForm}`
  const py = mode === 'json'
    ? `import requests\n\nr = requests.post(\n    "${url}",\n    headers={"X-API-Key": "${keyPlaceholder}"},\n    json={"context": ${ctx}${recipeJson}},\n    timeout=${Number(timeout) + 5 || 30},\n)\nreport = r.json()\nprint(r.status_code, report["status"], report["outputs"])`
    : `import requests\n\nwith open("part.png", "rb") as f:\n    r = requests.post(\n        "${url}",\n        headers={"X-API-Key": "${keyPlaceholder}"},\n        files={"image": f},\n        data={"context": '${ctx}'${recipe ? `, "recipe": "${recipe}"` : ''}},\n        timeout=${Number(timeout) + 5 || 30},\n    )\nreport = r.json()\nprint(r.status_code, report["status"], report["outputs"])`
  const cs = mode === 'json'
    ? `using var http = new HttpClient();\nhttp.DefaultRequestHeaders.Add("X-API-Key", "${keyPlaceholder}");\nvar body = new StringContent("{\\"context\\": ${ctx.replace(/"/g, '\\"')}}", Encoding.UTF8, "application/json");\nvar resp = await http.PostAsync("${url}", body);\nvar json = await resp.Content.ReadAsStringAsync();\nConsole.WriteLine($"{(int)resp.StatusCode} {json}");`
    : `using var http = new HttpClient();\nhttp.DefaultRequestHeaders.Add("X-API-Key", "${keyPlaceholder}");\nusing var form = new MultipartFormDataContent();\nform.Add(new ByteArrayContent(File.ReadAllBytes("part.png")), "image", "part.png");\nform.Add(new StringContent("${ctx.replace(/"/g, '\\"')}"), "context");\nvar resp = await http.PostAsync("${url}", form);\nvar json = await resp.Content.ReadAsStringAsync();\nConsole.WriteLine($"{(int)resp.StatusCode} {json}");`
  return { curl, py, cs }
}

function HttpSection({ info }: { info: IntegrationInfo }) {
  const { t } = useTranslation()
  const toast = useToast()
  const flows = useFlows()
  const [flowId, setFlowId] = useState('')
  const [mode, setMode] = useState<'json' | 'file'>('json')
  const [context, setContext] = useState('{}')
  const [recipe, setRecipe] = useState('')
  const [wait, setWait] = useState(true)
  const [timeout, setTimeout_] = useState('30')
  const [images, setImages] = useState(true)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [lang, setLang] = useState<'curl' | 'py' | 'cs'>('curl')
  const [result, setResult] = useState<{ status: number; ms: number; body: unknown } | null>(null)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    if (!flowId && flows.data?.items.length) setFlowId(String(flows.data.items[0].id))
  }, [flows.data, flowId])

  const keyPlaceholder = apiKey() ? '<YOUR_API_KEY>' : info.api_key_required ? '<YOUR_API_KEY>' : '(not required)'
  const code = useMemo(() => snippets(info.http_base, flowId, mode, context, wait, timeout, images, keyPlaceholder, recipe.trim()), [info.http_base, flowId, mode, context, wait, timeout, images, keyPlaceholder, recipe])

  async function send() {
    if (!flowId) return toast.error(t('integration.http.noFlow'))
    let ctx: unknown = null
    if (context.trim()) {
      try {
        ctx = JSON.parse(context)
      } catch {
        return toast.error(t('integration.http.contextInvalid'))
      }
    }
    setBusy(true)
    const qs = new URLSearchParams({ wait: wait ? '1' : '0', trigger: 'integration' })
    if (wait && timeout) qs.set('timeout', timeout)
    if (images) qs.set('include_images', '1')
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (apiKey()) headers['X-API-Key'] = apiKey()
    if (authToken()) headers.Authorization = `Bearer ${authToken()}`
    let body: BodyInit
    if (mode === 'file' && file) {
      const form = new FormData()
      form.append('image', file)
      if (ctx) form.append('context', JSON.stringify(ctx))
      if (recipe.trim()) form.append('recipe', recipe.trim())
      body = form
    } else {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify({ context: ctx, wait, ...(recipe.trim() ? { recipe: recipe.trim() } : {}) })
    }
    const t0 = performance.now()
    try {
      const resp = await fetch(`${BASE_URL}/vision/flows/${flowId}/run?${qs.toString()}`, { method: 'POST', headers, body })
      let parsed: unknown
      try {
        parsed = await resp.json()
      } catch {
        parsed = await resp.text()
      }
      setResult({ status: resp.status, ms: Math.round(performance.now() - t0), body: parsed })
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const refs = useMemo(() => {
    const out: { key: string; ref: string }[] = []
    const b = result?.body as { outputs?: Record<string, unknown>; nodes?: Record<string, { outputs?: Record<string, unknown> }> } | undefined
    if (!b || typeof b !== 'object') return out
    for (const [k, v] of Object.entries(b.outputs ?? {})) if (isImageRef(v) && v.ref) out.push({ key: k, ref: v.ref })
    for (const [nid, n] of Object.entries(b.nodes ?? {})) for (const [k, v] of Object.entries(n?.outputs ?? {})) if (isImageRef(v) && v.ref) out.push({ key: `${nid}.${k}`, ref: v.ref })
    return out.slice(0, 8)
  }, [result])

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title={t('integration.tabs.http')} />
        <CardBody className="space-y-3">
          <Select label={t('integration.http.flow')} value={flowId} onChange={(e) => setFlowId(e.target.value)} options={(flows.data?.items ?? []).map((f) => ({ value: String(f.id), label: `#${f.id} ${f.name}${f.is_enabled ? '' : `（${t('common.disabled')}）`}` }))} data-testid="http-flow" />
          <Select label={t('integration.http.mode')} value={mode} onChange={(e) => setMode(e.target.value as 'json' | 'file')} options={[{ value: 'json', label: t('integration.http.modeJson') }, { value: 'file', label: t('integration.http.modeFile') }]} />
          {mode === 'file' ? (
            <div className="flex items-center gap-2 text-xs">
              <input type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" data-testid="http-file" />
              {file ? <span className="text-muted">{file.name}</span> : null}
            </div>
          ) : null}
          <TextArea label={t('integration.http.context')} rows={3} className="font-mono text-xs" value={context} onChange={(e) => setContext(e.target.value)} data-testid="http-context" />
          <TextInput label={t('integration.http.recipe')} hint={t('integration.http.recipeHint')} value={recipe} onChange={(e) => setRecipe(e.target.value)} data-testid="http-recipe" />
          <div className="flex flex-wrap items-end gap-4">
            <Checkbox label={t('integration.http.wait')} checked={wait} onChange={setWait} />
            <TextInput label={t('integration.http.timeout')} type="number" min={1} className="!w-24 !py-1 text-xs" value={timeout} onChange={(e) => setTimeout_(e.target.value)} disabled={!wait} />
            <Checkbox label={t('integration.http.includeImages')} checked={images} onChange={setImages} />
          </div>
          <Button variant="primary" icon={<Send size={14} />} loading={busy} onClick={() => void send()} data-testid="http-send">{t('integration.http.send')}</Button>
          {result ? (
            <div className="space-y-2" data-testid="http-result">
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <span>{t('integration.http.status')}：<Badge tone={result.status < 300 ? 'ok' : result.status < 500 ? 'warning' : 'critical'}>{result.status}</Badge></span>
                <span className="tnum">{t('integration.http.elapsed')}：{result.ms} ms</span>
                <button type="button" className="text-muted hover:underline" onClick={() => setCollapsed((v) => !v)}>{collapsed ? '▸' : '▾'} {t('integration.http.response')}</button>
                <CopyButton text={JSON.stringify(result.body, null, 2)} />
              </div>
              {!collapsed ? <pre className="max-h-80 overflow-auto rounded-lg bg-surface-muted p-3 font-mono text-[11px] leading-relaxed">{JSON.stringify(result.body, null, 2)}</pre> : null}
              {refs.length ? (
                <div>
                  <p className="label">{t('integration.http.images')}</p>
                  <div className="flex flex-wrap gap-2">
                    {refs.map((r) => (
                      <figure key={r.key} className="text-center text-[10px] text-muted">
                        <img src={imageUrl(r.ref, 160)} alt={r.key} className="h-20 rounded bg-surface-muted object-contain" />
                        <figcaption className="max-w-40 truncate font-mono">{r.key}</figcaption>
                      </figure>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('integration.http.snippets')} actions={<Tabs size="sm" className="!border-0" value={lang} onChange={setLang} tabs={[{ value: 'curl', label: 'curl' }, { value: 'py', label: 'Python' }, { value: 'cs', label: 'C#' }]} />} />
        <CardBody>
          <CodeBlock code={code[lang]} />
        </CardBody>
      </Card>
    </div>
  )
}


export function HttpPage() {
  const info = useSectionInfo()
  if (!info) return <LoadingState />
  return (
    <div className="space-y-4">
      <HttpSection info={info} />
      <TraceLog channel="http" />
    </div>
  )
}
