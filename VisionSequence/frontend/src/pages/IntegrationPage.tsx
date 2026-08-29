/**
 * 整合頁（IntegrationPage）`/integration`：給外部整合方的說明與測試工具。
 * 分頁：HTTP API 測試（含 curl／Python／C# 片段）、TCP 測試（POST /integration/tcp）、事件監看（/events SSE）、
 * 鎖定、回傳格式。整合資訊來自 GET /integration/info。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { Cable, Check, Copy, Pause, Play, Plug, Send, Trash2 } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, CardBody, CardHeader, Checkbox, DetailRow, PageHeader, Select, StatusBadge, TextArea, TextInput, Tabs } from '@/components/ui'
import { apiKey, authToken, imageUrl, streamUrl } from '@/lib/api'
import { watchdog } from '@/lib/flowStream'
import { errorMessage } from '@/lib/errors'
import { useFlows, useIntegrationInfo, useTcpCommand } from '@/lib/queries'
import { isImageRef, type IntegrationInfo, type TcpResult } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

type IntegrationTab = 'http' | 'tcp' | 'events' | 'lock' | 'format' | 'plc'
const TABS: IntegrationTab[] = ['http', 'tcp', 'events', 'lock', 'format', 'plc']
const TCP_HISTORY_KEY = 'vs.tcpHistory'
const MAX_EVENTS = 200

/** 複製到剪貼簿：Clipboard API 不可用（非 https、權限被拒）時退回 execCommand。 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* 退回下面的方式 */
  }
  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(area)
    return ok
  } catch {
    return false
  }
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const [done, setDone] = useState(false)
  return (
    <Button
      size="xs"
      icon={done ? <Check size={12} /> : <Copy size={12} />}
      onClick={() => {
        void copyText(text).then((ok) => {
          if (!ok) {
            toast.error(t('errors.generic'))
            return
          }
          setDone(true)
          window.setTimeout(() => setDone(false), 1200)
        })
      }}
    >
      {done ? t('common.copied') : t('common.copy')}
    </Button>
  )
}

function CodeBlock({ code, title }: { code: string; title?: string }) {
  return (
    <div className="relative">
      {title ? <p className="mb-1 text-xs font-medium text-muted">{title}</p> : null}
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-muted p-3 pr-20 font-mono text-[11px] leading-relaxed">{code}</pre>
      <span className="absolute right-2 top-1"><CopyButton text={code} /></span>
    </div>
  )
}

function InfoBar({ info }: { info: IntegrationInfo }) {
  const { t } = useTranslation()
  return (
    <Card className="mb-4 px-4 py-2">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs" data-testid="integration-info">
        <span><span className="text-muted">{t('integration.info.httpBase')}：</span><code className="font-mono">{info.http_base}</code></span>
        <span className="flex items-center gap-1">
          <span className="text-muted">{t('integration.info.tcp')}：</span><code className="font-mono">{info.tcp_host}:{info.tcp_port}</code>
          <Badge tone={info.tcp_listening ? 'ok' : 'warning'}>{info.tcp_listening ? t('integration.info.listening') : t('integration.info.notListening')}</Badge>
        </span>
        <span><span className="text-muted">{t('integration.info.apiKey')}：</span>{info.api_key_required ? t('integration.info.required') : t('integration.info.optional')}</span>
        <span><span className="text-muted">{t('integration.info.workers')}：</span>{info.max_workers}</span>
        <span><span className="text-muted">{t('integration.info.timeout')}：</span>{info.run_timeout_s}</span>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
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

function HttpTab({ info }: { info: IntegrationInfo }) {
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
      const resp = await fetch(`/api/vision/flows/${flowId}/run?${qs.toString()}`, { method: 'POST', headers, body })
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

// ---------------------------------------------------------------------------
// 分頁 2：TCP 測試
// ---------------------------------------------------------------------------
function readHistory(): string[] {
  try {
    const raw = localStorage.getItem(TCP_HISTORY_KEY)
    return raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    return []
  }
}

function TcpTab({ info }: { info: IntegrationInfo }) {
  const { t } = useTranslation()
  const toast = useToast()
  const tcp = useTcpCommand()
  const flows = useFlows()
  const [command, setCommand] = useState('PING')
  const [history, setHistory] = useState<string[]>(readHistory)
  const [results, setResults] = useState<TcpResult[]>([])

  const common = useMemo(() => {
    const first = flows.data?.items[0]
    const id = first ? String(first.id) : '1'
    const list = info.commands.map((c) => c.replace('<flow>', id).replace(' [k=v ...]', '').replace(' [flow]', ''))
    const runIdx = list.findIndex((c) => c.startsWith('RUN '))
    list.splice(runIdx >= 0 ? runIdx + 1 : list.length, 0, `RUN ${id} recipe=<name>`)
    return list
  }, [info.commands, flows.data])

  async function send(cmd = command) {
    const line = cmd.trim()
    if (!line) return
    try {
      const res = await tcp.mutateAsync({ command: line })
      setResults((old) => [res, ...old].slice(0, 20))
      setHistory((old) => {
        const next = [line, ...old.filter((h) => h !== line)].slice(0, 30)
        try {
          localStorage.setItem(TCP_HISTORY_KEY, JSON.stringify(next))
        } catch {
          /* ignore */
        }
        return next
      })
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const latest = results[0]
  const howto = t('integration.tcp.howtoLines', { returnObjects: true, host: info.tcp_host === '0.0.0.0' ? info.host : info.tcp_host, port: info.tcp_port }) as unknown as string[]

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title={t('integration.tabs.tcp')} />
        <CardBody className="space-y-3">
          <div className="flex items-end gap-2">
            <TextInput label={t('integration.tcp.command')} className="font-mono" value={command} onChange={(e) => setCommand(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void send()} list="tcp-common" data-testid="tcp-command" />
            <datalist id="tcp-common">{common.map((c) => <option key={c} value={c} />)}</datalist>
            <Button variant="primary" icon={<Send size={14} />} loading={tcp.isPending} onClick={() => void send()} data-testid="tcp-send">{t('integration.tcp.send')}</Button>
          </div>
          <div className="flex flex-wrap gap-1">
            <span className="mr-1 text-xs text-muted">{t('integration.tcp.common')}：</span>
            {common.map((c) => (
              <button key={c} type="button" className="rounded border border-line bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] hover:border-brand" onClick={() => setCommand(c)}>{c}</button>
            ))}
          </div>
          {latest ? (
            <div className="space-y-1" data-testid="tcp-result">
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <code className="font-mono">{latest.command}</code>
                <span className="tnum">{latest.elapsed_ms} ms</span>
                <Badge tone={latest.via === 'tcp' ? 'ok' : 'warning'}>{t('integration.tcp.via')}：{latest.via}</Badge>
                <CopyButton text={JSON.stringify(latest.response, null, 2)} />
              </div>
              {latest.via === 'direct' ? <p className="rounded bg-warning-soft px-2 py-1 text-xs text-warning">{t('integration.tcp.viaDirect')}</p> : <p className="text-[11px] text-muted">{t('integration.tcp.viaTcp', { port: latest.tcp_port })}</p>}
              <pre className="max-h-72 overflow-auto rounded-lg bg-surface-muted p-3 font-mono text-[11px] leading-relaxed">{JSON.stringify(latest.response, null, 2)}</pre>
            </div>
          ) : null}
          {history.length ? (
            <div>
              <div className="mb-1 flex items-center justify-between">
                <p className="label !mb-0">{t('integration.tcp.history')}</p>
                <button type="button" className="text-[11px] text-muted hover:underline" onClick={() => { setHistory([]); localStorage.removeItem(TCP_HISTORY_KEY) }}>{t('integration.tcp.clearHistory')}</button>
              </div>
              <ul className="max-h-40 divide-y divide-line overflow-y-auto rounded-lg border border-line text-xs" data-testid="tcp-history">
                {history.map((h) => (
                  <li key={h} className="flex items-center gap-2 px-2 py-1">
                    <code className="flex-1 truncate font-mono">{h}</code>
                    <Button size="xs" onClick={() => { setCommand(h); void send(h) }}>{t('integration.tcp.resend')}</Button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('integration.tcp.howto')} />
        <CardBody>
          <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed">
            {(Array.isArray(howto) ? howto : []).map((line, i) => <li key={i} className="break-words">{line}</li>)}
          </ol>
          <CodeBlock title="Python socket" code={`import socket, json\n\ns = socket.create_connection(("${info.tcp_host === '0.0.0.0' ? info.host : info.tcp_host}", ${info.tcp_port}), timeout=30)\ns.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)\ns.sendall(b"RUN 1\\n")\nline = b""\nwhile not line.endswith(b"\\n"):\n    line += s.recv(65536)\nprint(json.loads(line))`} />
        </CardBody>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 分頁 3：事件監看
// ---------------------------------------------------------------------------
interface WatchedEvent {
  seq: number
  time: string
  type: string
  flow: string
  status: string
  ms: number | null
  detail: string
}

function EventsTab() {
  const { t } = useTranslation()
  const flows = useFlows()
  const [events, setEvents] = useState<WatchedEvent[]>([])
  const [paused, setPaused] = useState(false)
  const [connected, setConnected] = useState(false)
  const pausedRef = useRef(paused)
  pausedRef.current = paused
  const counter = useRef(0)
  const names = useMemo(() => new Map((flows.data?.items ?? []).map((f) => [f.id, f.name])), [flows.data])
  const namesRef = useRef(names)
  namesRef.current = names

  useEffect(() => {
    let source: EventSource | null = null
    let timer: number | undefined
    let closed = false
    let stopWatchdog: (() => void) | undefined
    const open = () => {
      if (closed) return
      source = new EventSource(streamUrl(null, undefined, true))
      stopWatchdog?.()
      stopWatchdog = watchdog(source, () => {
        setConnected(false)
        source?.close()
        if (!closed) timer = window.setTimeout(open, 5000)
      })
      source.addEventListener('open', () => setConnected(true))
      for (const type of ['run_queued', 'run_started', 'run_finished', 'continuous', 'stats', 'lock', 'cleared']) {
        source.addEventListener(type, (e) => {
          if (pausedRef.current) return
          let data: Record<string, unknown> = {}
          try {
            data = JSON.parse((e as MessageEvent).data) as Record<string, unknown>
          } catch {
            /* ignore */
          }
          const run = data.run as { status?: string; duration_ms?: number; outputs?: Record<string, unknown>; error?: string } | undefined
          const flowId = data.flow_id as number | undefined
          const lock = data.lock as { locked?: boolean; holder?: string } | undefined
          const item: WatchedEvent = {
            seq: (counter.current += 1),
            time: new Date().toLocaleTimeString(),
            type,
            flow: flowId !== undefined ? namesRef.current.get(flowId) ?? `#${flowId}` : '',
            status: run?.status ?? (type === 'continuous' ? (data.running ? 'running' : 'idle') : ''),
            ms: run?.duration_ms ?? null,
            detail: run ? run.error || JSON.stringify(run.outputs ?? {}).slice(0, 120) : lock ? `${lock.locked ? 'locked' : 'unlocked'} ${lock.holder ?? ''}` : JSON.stringify({ ...data, run: undefined }).slice(0, 120),
          }
          setEvents((old) => [item, ...old].slice(0, MAX_EVENTS))
        })
      }
      source.addEventListener('bye', () => {
        stopWatchdog?.()
        source?.close()
        timer = window.setTimeout(open, 50)
      })
      source.onerror = () => {
        setConnected(false)
        stopWatchdog?.()
        source?.close()
        if (!closed) timer = window.setTimeout(open, 5000)
      }
    }
    open()
    return () => {
      closed = true
      stopWatchdog?.()
      source?.close()
      window.clearTimeout(timer)
    }
  }, [])

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title={t('integration.tabs.events')}
        description={t('integration.events.hint')}
        actions={
          <>
            <Badge tone={connected ? 'ok' : 'neutral'}>{connected ? t('integration.events.connected') : t('integration.events.disconnected')}</Badge>
            <Button size="sm" icon={paused ? <Play size={13} /> : <Pause size={13} />} onClick={() => setPaused((v) => !v)} data-testid="events-pause">{paused ? t('integration.events.resume') : t('integration.events.pause')}</Button>
            <Button size="sm" icon={<Trash2 size={13} />} onClick={() => setEvents([])}>{t('integration.events.clear')}</Button>
          </>
        }
      />
      <div className="max-h-[60vh] overflow-auto">
        <table className="w-full text-xs" data-testid="events-table">
          <thead className="sticky top-0 bg-surface-muted text-[10px] uppercase text-subtle">
            <tr>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.time')}</th>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.type')}</th>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.flow')}</th>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.status')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('integration.events.cols.ms')}</th>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.detail')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {events.length === 0 ? <tr><td colSpan={6} className="px-3 py-8 text-center text-muted">{t('integration.events.empty')}</td></tr> : null}
            {events.map((e) => (
              <tr key={e.seq} data-testid="event-row">
                <td className="tnum whitespace-nowrap px-3 py-1">{e.time}</td>
                <td className="px-3 py-1 font-mono">{e.type}</td>
                <td className="max-w-[160px] truncate px-3 py-1">{e.flow}</td>
                <td className="px-3 py-1">{e.status ? <StatusBadge status={e.status} /> : null}</td>
                <td className="tnum px-3 py-1 text-right">{e.ms === null ? '' : Math.round(e.ms)}</td>
                <td className="max-w-[360px] truncate px-3 py-1 font-mono text-[10px] text-muted" title={e.detail}>{e.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// 分頁 4：鎖定
// ---------------------------------------------------------------------------
function LockTab({ info }: { info: IntegrationInfo }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const lock = auth.lock
  const base = info.http_base
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title={t('integration.lockTab.current')} description={t('integration.lockTab.hint')} />
        <CardBody className="space-y-3">
          <dl>
            <DetailRow label={t('lock.title')}><Badge tone={lock.locked ? 'warning' : 'ok'}>{lock.locked ? t('lock.locked') : t('lock.unlocked')}</Badge></DetailRow>
            {lock.locked ? (
              <>
                <DetailRow label={t('lock.holder')}>{lock.holder === 'integrator' ? t('lock.integrator') : lock.holder}</DetailRow>
                <DetailRow label={t('lock.reason')}>{lock.reason || t('lock.noReason')}</DetailRow>
                <DetailRow label={t('lock.ttl')}>{lock.expires_at ? new Date(lock.expires_at).toLocaleString() : '∞'}</DetailRow>
              </>
            ) : null}
          </dl>
          <Link to="/settings" className="text-xs text-brand hover:underline">{t('integration.lockTab.goSettings')}</Link>
        </CardBody>
      </Card>
      <Card>
        <CardBody className="space-y-3">
          <CodeBlock title={t('integration.lockTab.lockExample')} code={`curl -X POST "${base}/vision/lock" \\\n  -H "X-API-Key: <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"reason": "camera calibration", "ttl_s": 600}'`} />
          <CodeBlock title={t('integration.lockTab.unlockExample')} code={`curl -X DELETE "${base}/vision/lock" -H "X-API-Key: <YOUR_API_KEY>"`} />
          <CodeBlock title={t('integration.lockTab.statusExample')} code={`curl "${base}/vision/lock" -H "X-API-Key: <YOUR_API_KEY>"\n# → {"locked": true, "holder": "integrator", "reason": "...", "locked_at": "...", "expires_at": "..."}`} />
        </CardBody>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 分頁 5：回傳格式
// ---------------------------------------------------------------------------
const RUN_REPORT_FIELDS: [string, string, string][] = [
  ['id', 'string', 'run id（uuid hex）'],
  ['flow_id / flow_version', 'int', '流程與執行時的版本'],
  ['trigger', 'string', 'ui / api / tcp / continuous / preview / integration…'],
  ['status', '"ok" | "ng" | "failed" | "cancelled"', 'OK／NG 為判定結果；failed 為工具錯誤、逾時或沒有影像'],
  ['started_at / finished_at', 'float', 'Unix 秒'],
  ['duration_ms', 'float', '總耗時'],
  ['error', 'string', '失敗原因（成功為空字串）'],
  ['outputs', 'object', '具名輸出（見下表）'],
  ['nodes', 'object', '每個步驟的 {status, duration_ms, message, branch, outputs, overlays, detail, logs}'],
  ['persisted', 'bool', 'true = 來自資料庫歷史（GET /runs/{id}）'],
]

const ERROR_CODES: [string, string, string][] = [
  ['engine_locked', '423', '引擎被鎖定；details 是 lock 物件'],
  ['flow_queue_full', '429', '該流程等待中的執行已達上限，稍後重送'],
  ['flow_disabled', '409', '流程已停用（外部觸發被拒）'],
  ['flow_not_found', '404', 'flow id 不存在或無權限'],
  ['run_not_found', '404', 'run 不在記憶體也不在資料庫'],
  ['image_gone', '404', '影像 ref 已被快取淘汰（KEEP_RUN_IMAGES）'],
  ['bad_image', '422', '無法解碼影像'],
  ['too_many_images', '422', '批次測試超過 50 張'],
  ['validation_error', '422', '參數不合法'],
  ['unauthenticated / unauthorized', '401', '缺少或錯誤的權杖／API 金鑰'],
  ['permission_denied / not_owner', '403', '沒有修改權限'],
  ['capacity', '503', '執行緒池已滿'],
]

function FormatTab() {
  const { t } = useTranslation()
  const head = (cols: string[]) => (
    <thead><tr>{cols.map((c) => <th key={c} className="table-header">{c}</th>)}</tr></thead>
  )
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t('integration.format.runReport')} />
        <CardBody className="!p-0">
          <table className="w-full text-sm">
            {head([t('integration.format.cols.field'), t('integration.format.cols.type'), t('integration.format.cols.desc')])}
            <tbody className="divide-y divide-line">{RUN_REPORT_FIELDS.map(([f, ty, d]) => <tr key={f}><td className="table-cell font-mono text-xs">{f}</td><td className="table-cell font-mono text-xs text-muted">{ty}</td><td className="table-cell">{d}</td></tr>)}</tbody>
          </table>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('integration.format.outputs')} description={t('integration.format.outputsHint')} />
        <CardBody>
          <CodeBlock code={`{\n  "status": "ng",\n  "outputs": {\n    "hole_count": 3,\n    "judge": "NG",\n    "result_image": {"ref": "run:abc:n5:image", "width": 640, "height": 480}\n  },\n  "duration_ms": 12.3\n}`} />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('integration.format.errors')} />
        <CardBody className="!p-0">
          <table className="w-full text-sm">
            {head([t('integration.format.cols.code'), t('integration.format.cols.http'), t('integration.format.cols.when')])}
            <tbody className="divide-y divide-line">{ERROR_CODES.map(([c, h, w]) => <tr key={c}><td className="table-cell font-mono text-xs">{c}</td><td className="table-cell tnum">{h}</td><td className="table-cell">{w}</td></tr>)}</tbody>
          </table>
          <p className="px-4 py-3 text-xs text-muted">{'{"error": {"code": "...", "message": "...", "details": ...}}'}</p>
        </CardBody>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 分頁 6：PLC 輸出（write_plc 的 mapping 格式＋連到連線頁）
// ---------------------------------------------------------------------------
function PlcTab() {
  const { t } = useTranslation()
  const lines = (key: string) => t(key, { returnObjects: true }) as unknown as string[]
  const example = `[
  {"src": "judge", "address": "coil:0", "dtype": "bool"},
  {"src": "count", "address": "holding:100", "dtype": "int"},
  {"src": "area", "address": "holding:102:float32", "scale": 0.01},
  {"src": "v0", "address": "holding:110", "dtype": "int", "offset": 1},
  {"value": 1, "address": "coil:7"}
]`
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title={<span className="flex items-center gap-2"><Cable size={16} className="text-brand" />{t('integration.plc.title')}</span>} actions={<Link to="/connections" className="btn-secondary !h-8 !px-2.5 !text-xs" data-testid="plc-go-connections"><Plug size={13} /> {t('integration.plc.goConnections')}</Link>} />
        <CardBody className="space-y-3 text-sm leading-relaxed">
          <p>{t('integration.plc.intro')}</p>
          <div>
            <p className="label">{t('integration.plc.srcTitle')}</p>
            <ul className="list-disc space-y-1 pl-5 text-xs">{(Array.isArray(lines('integration.plc.srcLines')) ? lines('integration.plc.srcLines') : []).map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
          <div>
            <p className="label">{t('integration.plc.addressTitle')}</p>
            <ul className="list-disc space-y-1 pl-5 text-xs">{(Array.isArray(lines('integration.plc.addressLines')) ? lines('integration.plc.addressLines') : []).map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
          <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">{t('integration.plc.degrade')}</p>
          <p className="text-xs text-muted">{t('integration.plc.docs')}</p>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('integration.plc.mappingTitle')} description={t('integration.plc.mappingHint')} />
        <CardBody>
          <CodeBlock title={t('integration.plc.example')} code={example} />
        </CardBody>
      </Card>
    </div>
  )
}

export function IntegrationPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const initial = params.get('tab') as IntegrationTab | null
  const [tab, setTab] = useState<IntegrationTab>(initial && TABS.includes(initial) ? initial : 'http')
  const info = useIntegrationInfo()
  const change = (next: IntegrationTab) => {
    setTab(next)
    setParams({ tab: next }, { replace: true })
  }
  return (
    <Page wide>
      <PageHeader title={<span className="flex items-center gap-2"><Plug size={20} className="text-brand" />{t('integration.title')}</span>} description={t('integration.subtitle')} />
      {info.data ? <InfoBar info={info.data} /> : null}
      <Tabs value={tab} onChange={change} tabs={TABS.map((value) => ({ value, label: t(`integration.tabs.${value}`) }))} className="mb-4 flex-wrap" />
      <div data-testid={`integration-${tab}`}>
        {tab === 'http' && info.data ? <HttpTab info={info.data} /> : null}
        {tab === 'tcp' && info.data ? <TcpTab info={info.data} /> : null}
        {tab === 'events' ? <EventsTab /> : null}
        {tab === 'lock' && info.data ? <LockTab info={info.data} /> : null}
        {tab === 'format' ? <FormatTab /> : null}
        {tab === 'plc' ? <PlcTab /> : null}
      </div>
    </Page>
  )
}
