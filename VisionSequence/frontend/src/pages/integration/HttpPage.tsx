/**
 * 整合 ▸ HTTP API：Swagger 風格的 API 總覽（從伺服器的 OpenAPI 描述產生：依 tag 分組、每個端點展開看參數與
 * 請求本文、Try it out 直接用目前的登入身分打），加上回傳格式與錯誤碼、命令與結果。
 * 整合方最常用的端點排最前面並附白話說明（i18n integration.http.ops.*）。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Activity, ChevronDown, ChevronRight, FileJson, Play, Send } from 'lucide-react'

import { CodeBlock, CopyButton, SectionTabs, useSectionInfo } from './shared'
import { buildCurl, essentialKey, exampleFromSchema, fillPath, groupByTag, listOperations, matches, queryString, typeOf, type Method, type OpenApiDocument, type Operation } from './openapi'
import { TraceLog } from '@/components/integration/TraceLog'
import { Badge, Button, Card, CardBody, CardHeader, ErrorState, LoadingState, TextArea, TextInput } from '@/components/ui'
import { BASE_URL, apiKey, authToken, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useFlows, useOpenApi } from '@/lib/queries'
import { isImageRef, type IntegrationInfo } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

/** Swagger UI 的方法色：GET 藍、POST 綠、PATCH 青、PUT 橘、DELETE 紅。 */
const METHOD_STYLE: Record<Method, string> = {
  get: 'bg-sky-600 text-white',
  post: 'bg-emerald-600 text-white',
  put: 'bg-amber-500 text-white',
  patch: 'bg-teal-500 text-white',
  delete: 'bg-rose-600 text-white',
}

/** RunReport 欄位：[顯示名稱, 型別, i18n 鍵]；說明文字在 integration.format.fields.* */
const RUN_REPORT_FIELDS: [string, string, string][] = [
  ['id', 'string', 'id'],
  ['flow_id / flow_version', 'int', 'flow'],
  ['trigger', 'string', 'trigger'],
  ['status', '"ok" | "ng" | "failed" | "cancelled"', 'status'],
  ['started_at / finished_at', 'float', 'time'],
  ['duration_ms', 'float', 'duration'],
  ['error', 'string', 'error'],
  ['outputs', 'object', 'outputs'],
  ['nodes', 'object', 'nodes'],
  ['persisted', 'bool', 'persisted'],
]

/** 錯誤碼：[code, HTTP 狀態, i18n 鍵]；說明文字在 integration.format.errorCodes.* */
const ERROR_CODES: [string, string, string][] = [
  ['engine_locked', '423', 'engine_locked'],
  ['flow_queue_full', '429', 'flow_queue_full'],
  ['run_timeout', '504', 'run_timeout'],
  ['flow_disabled', '409', 'flow_disabled'],
  ['flow_not_found', '404', 'flow_not_found'],
  ['run_not_found', '404', 'run_not_found'],
  ['image_gone', '404', 'image_gone'],
  ['bad_image', '422', 'bad_image'],
  ['too_many_images', '422', 'too_many_images'],
  ['validation_error', '422', 'validation_error'],
  ['unauthenticated / unauthorized', '401', 'unauthenticated'],
  ['permission_denied / not_owner', '403', 'permission_denied'],
  ['capacity', '503', 'capacity'],
]

/** 回傳格式：RunReport 欄位、具名輸出範例與錯誤碼（設備請用 code 分支）。 */
function FormatCards() {
  const { t } = useTranslation()
  return (
    <div className="grid items-start gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title={t('integration.format.runReport')} />
        <CardBody className="!p-0">
          <table className="w-full text-sm">
            <thead><tr><th className="table-header">{t('integration.format.cols.field')}</th><th className="table-header">{t('integration.format.cols.type')}</th><th className="table-header">{t('integration.format.cols.desc')}</th></tr></thead>
            <tbody className="divide-y divide-line">{RUN_REPORT_FIELDS.map(([f, ty, k]) => <tr key={f}><td className="table-cell font-mono text-xs">{f}</td><td className="table-cell font-mono text-xs text-muted">{ty}</td><td className="table-cell">{t(`integration.format.fields.${k}`)}</td></tr>)}</tbody>
          </table>
        </CardBody>
      </Card>
      <div className="space-y-4">
        <Card>
          <CardHeader title={t('integration.format.outputs')} description={t('integration.format.outputsHint')} />
          <CardBody>
            <CodeBlock code={'{\n  "status": "ng",\n  "outputs": {\n    "hole_count": 3,\n    "judge": "NG",\n    "result_image": {"ref": "run:abc:n5:image", "width": 640, "height": 480}\n  },\n  "duration_ms": 12.3\n}'} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('integration.format.errors')} />
          <CardBody className="!p-0">
            <table className="w-full text-sm">
              <thead><tr><th className="table-header">{t('integration.format.cols.code')}</th><th className="table-header">{t('integration.format.cols.http')}</th><th className="table-header">{t('integration.format.cols.when')}</th></tr></thead>
              <tbody className="divide-y divide-line">{ERROR_CODES.map(([c, h, k]) => <tr key={c}><td className="table-cell font-mono text-xs">{c}</td><td className="table-cell tnum">{h}</td><td className="table-cell">{t(`integration.format.errorCodes.${k}`)}</td></tr>)}</tbody>
            </table>
            <p className="px-4 py-3 text-xs text-muted">{'{"error": {"code": "...", "message": "...", "details": ...}}'}</p>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// API 總覽（Swagger 風格）
// ---------------------------------------------------------------------------
interface ExecResult { status: number; ms: number; body: unknown }

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (apiKey()) headers['X-API-Key'] = apiKey()
  if (authToken()) headers.Authorization = `Bearer ${authToken()}`
  return headers
}

/** 一個端點：摘要列（方法、路徑、名稱），展開後是參數、請求本文、回應與 Try it out。 */
function OperationRow({ operation, doc, info, defaults }: { operation: Operation; doc: OpenApiDocument; info: IntegrationInfo; defaults: Record<string, string> }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { method, path, op } = operation
  const [open, setOpen] = useState(false)
  const [trying, setTrying] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ExecResult | null>(null)
  const params = op.parameters ?? []
  const bodyEntry = Object.entries(op.requestBody?.content ?? {})[0]
  const contentType: 'json' | 'multipart' | undefined = bodyEntry ? (bodyEntry[0].includes('multipart') ? 'multipart' : 'json') : undefined
  const bodySchema = bodyEntry?.[1].schema
  const essential = essentialKey(method, path)
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {}
    for (const p of params) init[p.name] = defaults[p.name] ?? (p.schema?.default !== undefined && p.in === 'query' ? String(p.schema.default) : '')
    return init
  })
  const [body, setBody] = useState(() => (contentType === 'json' ? JSON.stringify(exampleFromSchema(bodySchema, doc) ?? {}, null, 2) : ''))
  const [form, setForm] = useState<Record<string, string>>(() => {
    const example = contentType === 'multipart' ? (exampleFromSchema(bodySchema, doc) as Record<string, unknown> | null) : null
    const init: Record<string, string> = {}
    for (const [k, v] of Object.entries(example ?? {})) init[k] = typeof v === 'string' ? v : JSON.stringify(v)
    if ('context' in init) init.context = '{}'
    return init
  })
  const [files, setFiles] = useState<Record<string, File | null>>({})

  const pathValues = Object.fromEntries(params.filter((p) => p.in === 'path').map((p) => [p.name, values[p.name] ?? '']))
  const queryValues = Object.fromEntries(params.filter((p) => p.in === 'query').map((p) => [p.name, values[p.name] ?? '']))
  const relative = fillPath(path, pathValues) + queryString(queryValues)
  const absolute = `${info.http_base.replace(/\/api$/, '')}${relative}`
  const keyHeader = apiKey() || info.api_key_required ? 'X-API-Key: <YOUR_API_KEY>' : 'Authorization: Bearer <TOKEN>'
  const curl = buildCurl({ method, url: absolute, keyHeader, contentType, body: contentType === 'json' ? body : undefined, form: contentType === 'multipart' ? form : undefined })

  async function execute() {
    const missing = params.filter((p) => p.in === 'path' && !values[p.name])
    if (missing.length) return toast.error(t('integration.explorer.missingPath', { name: missing[0].name }))
    const headers = authHeaders()
    let payload: BodyInit | undefined
    if (contentType === 'json') {
      try {
        payload = body.trim() ? JSON.stringify(JSON.parse(body)) : undefined
      } catch {
        return toast.error(t('integration.explorer.jsonInvalid'))
      }
      headers['Content-Type'] = 'application/json'
    } else if (contentType === 'multipart') {
      const fd = new FormData()
      for (const [k, v] of Object.entries(form)) {
        const file = files[k]
        if (file) fd.append(k, file)
        else if (v && v !== '(file)') fd.append(k, v)
      }
      payload = fd
    }
    setBusy(true)
    const t0 = performance.now()
    try {
      const resp = await fetch(`${BASE_URL}${relative.replace(/^\/api/, '')}`, { method: method.toUpperCase(), headers, body: payload })
      let parsed: unknown
      const text = await resp.text()
      try {
        parsed = JSON.parse(text)
      } catch {
        parsed = text
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

  const tone = result ? (result.status < 300 ? 'ok' : result.status < 500 ? 'warning' : 'critical') : 'neutral'
  return (
    <div className="border-b border-line last:border-b-0" data-testid={`op-${method}-${path}`}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-surface-muted/60">
        <span className={`w-16 shrink-0 rounded px-1.5 py-0.5 text-center text-[11px] font-bold uppercase ${METHOD_STYLE[method]}`}>{method}</span>
        <code className="min-w-0 flex-1 truncate font-mono text-sm">{path.replace(/^\/api/, '')}</code>
        <span className="hidden max-w-[40%] truncate text-xs text-muted md:inline">{essential ? t(`integration.http.ops.${essential}.summary`) : op.summary}</span>
        {open ? <ChevronDown size={14} className="shrink-0 text-muted" /> : <ChevronRight size={14} className="shrink-0 text-muted" />}
      </button>
      {open ? (
        <div className="space-y-3 border-t border-line bg-surface-muted/30 px-3 py-3 text-sm">
          {essential ? <p className="leading-relaxed">{t(`integration.http.ops.${essential}.desc`)}</p> : null}
          <div className="flex items-center justify-between">
            <p className="label !mb-0">{t('integration.explorer.parameters')}</p>
            {trying ? (
              <span className="flex gap-2">
                <Button size="xs" onClick={() => { setTrying(false); setResult(null) }}>{t('common.cancel')}</Button>
                <Button size="xs" variant="primary" icon={<Play size={12} />} loading={busy} onClick={() => void execute()} data-testid="op-execute">{t('integration.explorer.execute')}</Button>
              </span>
            ) : (
              <Button size="xs" onClick={() => setTrying(true)} data-testid="op-try">{t('integration.explorer.tryIt')}</Button>
            )}
          </div>
          {params.length ? (
            <table className="w-full text-xs">
              <thead><tr><th className="table-header">{t('integration.explorer.name')}</th><th className="table-header">{t('integration.explorer.in')}</th><th className="table-header">{t('integration.explorer.type')}</th><th className="table-header">{t('integration.explorer.value')}</th></tr></thead>
              <tbody className="divide-y divide-line">
                {params.map((p) => (
                  <tr key={`${p.in}-${p.name}`}>
                    <td className="table-cell font-mono">{p.name}{p.required ? <span className="ml-1 text-critical" title={t('integration.explorer.required')}>*</span> : null}</td>
                    <td className="table-cell text-muted">{p.in}</td>
                    <td className="table-cell font-mono text-muted">{typeOf(p.schema, doc)}{p.schema?.default !== undefined ? <span className="ml-1 text-subtle">= {JSON.stringify(p.schema.default)}</span> : null}</td>
                    <td className="table-cell">
                      {trying ? <TextInput className="!py-1 font-mono text-xs" value={values[p.name] ?? ''} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} placeholder={p.name} /> : <span className="font-mono text-muted">{values[p.name] || '—'}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-xs text-subtle">{t('integration.explorer.noParams')}</p>}
          {contentType ? (
            <div>
              <p className="label">{t('integration.explorer.body')} <span className="font-mono text-[11px] font-normal text-subtle">{bodyEntry?.[0]}</span></p>
              {contentType === 'json' ? (
                trying ? <TextArea rows={Math.min(12, body.split('\n').length + 1)} className="font-mono text-xs" value={body} onChange={(e) => setBody(e.target.value)} /> : <pre className="max-h-48 overflow-auto rounded-lg bg-surface p-2 font-mono text-[11px]">{body}</pre>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2">
                  {Object.entries(form).map(([k, v]) => (
                    <div key={k}>
                      {v === '(file)' || files[k] ? (
                        <label className="text-xs"><span className="label">{k} <span className="font-normal text-subtle">({t('integration.explorer.file')})</span></span>
                          <input type="file" disabled={!trying} className="text-xs" onChange={(e) => setFiles({ ...files, [k]: e.target.files?.[0] ?? null })} /></label>
                      ) : (
                        <TextInput label={k} className="!py-1 font-mono text-xs" disabled={!trying} value={v} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}
          <div>
            <p className="label">{t('integration.explorer.responses')}</p>
            <p className="text-xs text-muted">{Object.entries(op.responses ?? {}).map(([code, r]) => `${code} ${r.description ?? ''}`).join(' · ') || '200'}</p>
          </div>
          <CodeBlock title="curl" code={curl} />
          {result ? (
            <div className="space-y-2" data-testid="op-result">
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <span>{t('integration.explorer.status')}: <Badge tone={tone}>{result.status}</Badge></span>
                <span className="tnum">{t('integration.explorer.elapsed')}: {result.ms} ms</span>
                <CopyButton text={typeof result.body === 'string' ? result.body : JSON.stringify(result.body, null, 2)} />
              </div>
              <pre className="max-h-80 overflow-auto rounded-lg bg-surface p-3 font-mono text-[11px] leading-relaxed">{typeof result.body === 'string' ? result.body : JSON.stringify(result.body, null, 2)}</pre>
              {refs.length ? (
                <div className="flex flex-wrap gap-2">
                  {refs.map((r) => (
                    <figure key={r.key} className="text-center text-[10px] text-muted">
                      <img src={imageUrl(r.ref, 160)} alt={r.key} className="h-20 rounded bg-surface-muted object-contain" />
                      <figcaption className="max-w-40 truncate font-mono">{r.key}</figcaption>
                    </figure>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function TagGroup({ title, hint, items, doc, info, defaults, defaultOpen = false }: { title: string; hint?: string; items: Operation[]; doc: OpenApiDocument; info: IntegrationInfo; defaults: Record<string, string>; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <Card className="overflow-hidden">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-surface-muted/60" data-testid={`tag-${title}`}>
        {open ? <ChevronDown size={15} className="text-muted" /> : <ChevronRight size={15} className="text-muted" />}
        <span className="font-semibold">{title}</span>
        {hint ? <span className="truncate text-xs text-muted">{hint}</span> : null}
        <Badge className="ml-auto" tone="neutral">{items.length}</Badge>
      </button>
      {open ? <div className="border-t border-line">{items.map((o) => <OperationRow key={o.id} operation={o} doc={doc} info={info} defaults={defaults} />)}</div> : null}
    </Card>
  )
}

function ApiExplorer({ info }: { info: IntegrationInfo }) {
  const { t } = useTranslation()
  const spec = useOpenApi()
  const flows = useFlows()
  const [query, setQuery] = useState('')
  const ops = useMemo(() => (spec.data ? listOperations(spec.data) : []), [spec.data])
  const shown = useMemo(() => ops.filter((o) => matches(o, query)), [ops, query])
  const essentials = useMemo(() => shown.filter((o) => essentialKey(o.method, o.path)).sort((a, b) => a.path.localeCompare(b.path)), [shown])
  const groups = useMemo(() => groupByTag(shown), [shown])
  const defaults = useMemo(() => ({ flow_id: flows.data?.items[0] ? String(flows.data.items[0].id) : '' }), [flows.data])

  if (spec.isPending) return <LoadingState />
  if (spec.isError || !spec.data) return <ErrorState error={spec.error ?? new Error(t('integration.explorer.loadFailed'))} onRetry={() => void spec.refetch()} />
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={<span className="flex items-center gap-2"><Send size={16} className="text-brand" />{t('integration.explorer.title')}</span>}
          description={t('integration.explorer.hint')}
          actions={<a href={`${BASE_URL}/openapi.json`} target="_blank" rel="noreferrer" className="btn-secondary !h-8 !px-2.5 !text-xs">{t('integration.explorer.spec')}</a>}
        />
        <CardBody>
          <TextInput className="font-mono" placeholder={t('integration.explorer.search')} value={query} onChange={(e) => setQuery(e.target.value)} data-testid="api-search" />
        </CardBody>
      </Card>
      {essentials.length ? <TagGroup title={t('integration.explorer.essentials')} hint={t('integration.explorer.essentialsHint')} items={essentials} doc={spec.data} info={info} defaults={defaults} defaultOpen /> : null}
      {groups.map((g) => <TagGroup key={g.tag} title={g.tag} items={g.items} doc={spec.data!} info={info} defaults={defaults} defaultOpen={Boolean(query)} />)}
    </div>
  )
}

export function HttpPage() {
  const { t } = useTranslation()
  const info = useSectionInfo()
  if (!info) return <LoadingState />
  return (
    <SectionTabs section="http" tabs={[
      { key: 'try', label: t('integration.sections.try'), icon: Send, content: <ApiExplorer info={info} /> },
      { key: 'format', label: t('integration.sections.format'), icon: FileJson, content: <FormatCards /> },
      { key: 'trace', label: t('integration.trace.title'), icon: Activity, content: <TraceLog channel="http" /> },
    ]} />
  )
}
