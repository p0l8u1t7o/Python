/**
 * 整合 ▸ TCP：Swagger 風格的指令總覽（每個指令一列：語法、說明、引數、範例回應，展開後 Try it out 直接對本機送）、
 * 任意一行指令的送出框與歷史、失敗碼、送出結果用的 TCP 連線、命令與結果。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Activity, ChevronDown, ChevronRight, ListChecks, Play, Plug, Send, Terminal } from 'lucide-react'

import { CodeBlock, CopyButton, SectionTabs, connectHost, useSectionInfo } from './shared'
import { ConnectionsSection } from '@/components/integration/ConnectionsSection'
import { TraceLog } from '@/components/integration/TraceLog'
import { Badge, Button, Card, CardBody, CardHeader, LoadingState, TextInput } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useFlows, useTcpCommand } from '@/lib/queries'
import { useToast } from '@/providers/ToastProvider'
import type { IntegrationInfo, TcpResult } from '@/lib/types'

const TCP_HISTORY_KEY = 'vs.tcpHistory'

/** TCP 一行指令的失敗碼（設備請用 code 分支，說明文字會隨版本潤飾）；說明在 integration.format.tcpCodes.* */
const TCP_CODES = ['empty_command', 'unknown_command', 'missing_argument', 'bad_argument', 'flow_not_found', 'flow_disabled', 'flow_queue_full', 'recipe_not_found', 'engine_locked', 'internal_error'] as const

/**
 * 指令目錄（與 apps/vision/tcp_server.py 同步）：語法、引數（i18n integration.tcp.args.*）、範例與範例回應。
 * `{flow}` 會換成第一條流程的 id。
 */
const COMMANDS: { name: string; syntax: string; args: string[]; example: string; response: string }[] = [
  { name: 'PING', syntax: 'PING', args: [], example: 'PING', response: '{"ok": true, "pong": true}' },
  { name: 'AUTH', syntax: 'AUTH <key>', args: ['key'], example: 'AUTH <key>', response: '{"ok": true, "authenticated": true}' },
  { name: 'LIST', syntax: 'LIST', args: [], example: 'LIST', response: '{"ok": true, "flows": [{"id": 1, "name": "hole_count", "enabled": true}]}' },
  { name: 'VARS', syntax: 'VARS <flow|station>', args: ['target'], example: 'VARS {flow}', response: '{"ok": true, "scope": "hole_count", "items": {"parts": 128, "lot": "A17"}}' },
  { name: 'SET', syntax: 'SET <flow|station> key=value ...', args: ['target', 'setkv'], example: 'SET {flow} lot=A17 parts=0', response: '{"ok": true, "scope": "hole_count", "items": {"parts": 0, "lot": "A17"}}' },
  { name: 'STATUS', syntax: 'STATUS [flow]', args: ['flowOptional'], example: 'STATUS {flow}', response: '{"ok": true, "flow_id": 1, "stats": {"total": 120, "ok": 118, "ng": 2}, "continuous": false, "queued": 0, "running": false}' },
  { name: 'RUN', syntax: 'RUN <flow> [key=value ...] [fmt=<output>]', args: ['flow', 'kv', 'recipe', 'fmt'], example: 'RUN {flow} lot=A1', response: '{"ok": true, "status": "ok", "judge": "OK", "outputs": {"hole_count": 3}, "duration_ms": 12.3, "run_id": "…"}' },
  { name: 'TRIGGER', syntax: 'TRIGGER <flow> [key=value ...]', args: ['flow', 'kv', 'recipe'], example: 'TRIGGER {flow} lot=A1', response: '{"ok": true, "queued": true, "run_id": "…"}' },
  { name: 'START', syntax: 'START <flow>', args: ['flow'], example: 'START {flow}', response: '{"ok": true, "continuous": true}' },
  { name: 'STOP', syntax: 'STOP <flow>', args: ['flow'], example: 'STOP {flow}', response: '{"ok": true, "continuous": false}' },
  { name: 'LOCK', syntax: 'LOCK [reason="..."] [ttl=seconds]', args: ['reason', 'ttl'], example: 'LOCK reason="camera calibration" ttl=600', response: '{"ok": true, "lock": {"locked": true, "holder": "integrator", "reason": "camera calibration", "expires_at": "…"}}' },
  { name: 'UNLOCK', syntax: 'UNLOCK', args: [], example: 'UNLOCK', response: '{"ok": true, "lock": {"locked": false}}' },
]

function TcpCodesCard() {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader title={t('integration.format.tcpErrors')} description={t('integration.format.tcpErrorsHint')} />
      <CardBody className="!p-0">
        <table className="w-full text-sm">
          <thead><tr><th className="table-header">{t('integration.format.cols.code')}</th><th className="table-header">{t('integration.format.cols.desc')}</th></tr></thead>
          <tbody className="divide-y divide-line">{TCP_CODES.map((c) => <tr key={c}><td className="table-cell font-mono text-xs">{c}</td><td className="table-cell">{t(`integration.format.tcpCodes.${c}`)}</td></tr>)}</tbody>
        </table>
      </CardBody>
    </Card>
  )
}

function readHistory(): string[] {
  try {
    const raw = localStorage.getItem(TCP_HISTORY_KEY)
    return raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    return []
  }
}

function ResultBlock({ result }: { result: TcpResult }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-1" data-testid="tcp-result">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <code className="font-mono">{result.command}</code>
        <span className="tnum">{result.elapsed_ms} ms</span>
        <Badge tone={result.via === 'tcp' ? 'ok' : 'warning'}>{t('integration.tcp.via')}: {result.via}</Badge>
        <CopyButton text={JSON.stringify(result.response, null, 2)} />
      </div>
      {result.via === 'direct' ? <p className="rounded bg-warning-soft px-2 py-1 text-xs text-warning">{t('integration.tcp.viaDirect')}</p> : <p className="text-[11px] text-muted">{t('integration.tcp.viaTcp', { port: result.tcp_port })}</p>}
      <pre className="max-h-72 overflow-auto rounded-lg bg-surface p-3 font-mono text-[11px] leading-relaxed">{JSON.stringify(result.response, null, 2)}</pre>
    </div>
  )
}

/** 一個指令：摘要列展開後是說明、引數表、範例回應與 Try it out。 */
function CommandRow({ cmd, flowId, onSend }: { cmd: (typeof COMMANDS)[number]; flowId: string; onSend: (line: string) => Promise<TcpResult | null> }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [trying, setTrying] = useState(false)
  const [busy, setBusy] = useState(false)
  const [line, setLine] = useState(cmd.example.replace('{flow}', flowId))
  const [result, setResult] = useState<TcpResult | null>(null)

  async function execute() {
    setBusy(true)
    try {
      setResult(await onSend(line))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border-b border-line last:border-b-0" data-testid={`tcp-cmd-${cmd.name}`}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-surface-muted/60">
        <span className="w-16 shrink-0 rounded bg-violet-600 px-1.5 py-0.5 text-center text-[11px] font-bold text-white">TCP</span>
        <code className="min-w-0 flex-1 truncate font-mono text-sm">{cmd.syntax}</code>
        <span className="hidden max-w-[40%] truncate text-xs text-muted md:inline">{t(`integration.tcp.cmd.${cmd.name}.summary`)}</span>
        {open ? <ChevronDown size={14} className="shrink-0 text-muted" /> : <ChevronRight size={14} className="shrink-0 text-muted" />}
      </button>
      {open ? (
        <div className="space-y-3 border-t border-line bg-surface-muted/30 px-3 py-3 text-sm">
          <p className="leading-relaxed">{t(`integration.tcp.cmd.${cmd.name}.desc`)}</p>
          <div className="flex items-center justify-between">
            <p className="label !mb-0">{t('integration.explorer.parameters')}</p>
            {trying ? (
              <span className="flex gap-2">
                <Button size="xs" onClick={() => { setTrying(false); setResult(null) }}>{t('common.cancel')}</Button>
                <Button size="xs" variant="primary" icon={<Play size={12} />} loading={busy} onClick={() => void execute()} data-testid="tcp-execute">{t('integration.explorer.execute')}</Button>
              </span>
            ) : (
              <Button size="xs" onClick={() => setTrying(true)} data-testid="tcp-try">{t('integration.explorer.tryIt')}</Button>
            )}
          </div>
          {cmd.args.length ? (
            <table className="w-full text-xs">
              <thead><tr><th className="table-header">{t('integration.explorer.name')}</th><th className="table-header">{t('integration.explorer.description')}</th></tr></thead>
              <tbody className="divide-y divide-line">
                {cmd.args.map((a) => <tr key={a}><td className="table-cell font-mono">{t(`integration.tcp.args.${a}.name`)}</td><td className="table-cell">{t(`integration.tcp.args.${a}.desc`)}</td></tr>)}
              </tbody>
            </table>
          ) : <p className="text-xs text-subtle">{t('integration.explorer.noParams')}</p>}
          <div>
            <p className="label">{t('integration.explorer.request')}</p>
            {trying ? <TextInput className="font-mono" value={line} onChange={(e) => setLine(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void execute()} /> : <pre className="rounded-lg bg-surface p-2 font-mono text-[11px]">{line}</pre>}
          </div>
          <CodeBlock title={t('integration.explorer.exampleResponse')} code={cmd.response} />
          {result ? <ResultBlock result={result} /> : null}
        </div>
      ) : null}
    </div>
  )
}

function CommandExplorer({ info }: { info: IntegrationInfo }) {
  const { t } = useTranslation()
  const toast = useToast()
  const tcp = useTcpCommand()
  const flows = useFlows()
  const flowId = flows.data?.items[0] ? String(flows.data.items[0].id) : '1'
  const [command, setCommand] = useState('PING')
  const [history, setHistory] = useState<string[]>(readHistory)
  const [latest, setLatest] = useState<TcpResult | null>(null)
  const tcpHost = connectHost(info.tcp_connect_host, info.tcp_host, info.host)
  const howto = t('integration.tcp.howtoLines', { returnObjects: true, host: tcpHost, port: info.tcp_port }) as unknown as string[]

  async function send(cmd: string): Promise<TcpResult | null> {
    const trimmed = cmd.trim()
    if (!trimmed) return null
    try {
      const res = await tcp.mutateAsync({ command: trimmed })
      setHistory((old) => {
        const next = [trimmed, ...old.filter((h) => h !== trimmed)].slice(0, 30)
        try {
          localStorage.setItem(TCP_HISTORY_KEY, JSON.stringify(next))
        } catch {
          /* ignore */
        }
        return next
      })
      return res
    } catch (error) {
      toast.error(errorMessage(error))
      return null
    }
  }

  const commands = useMemo(() => COMMANDS, [])
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={<span className="flex items-center gap-2"><Terminal size={16} className="text-brand" />{t('integration.tcp.explorer.title')}</span>}
          description={t('integration.tcp.explorer.hint', { host: tcpHost, port: info.tcp_port })}
        />
        <CardBody className="space-y-3">
          <div className="flex items-end gap-2">
            <TextInput label={t('integration.tcp.command')} className="font-mono" value={command} onChange={(e) => setCommand(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void send(command).then((r) => r && setLatest(r))} data-testid="tcp-command" />
            <Button variant="primary" icon={<Send size={14} />} loading={tcp.isPending} onClick={() => void send(command).then((r) => r && setLatest(r))} data-testid="tcp-send">{t('integration.tcp.send')}</Button>
          </div>
          {latest ? <ResultBlock result={latest} /> : null}
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
                    <Button size="xs" onClick={() => { setCommand(h); void send(h).then((r) => r && setLatest(r)) }}>{t('integration.tcp.resend')}</Button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardBody>
      </Card>
      <Card className="overflow-hidden">
        <div className="border-b border-line px-4 py-2.5 text-sm font-semibold">{t('integration.tcp.explorer.commands')} <Badge className="ml-1" tone="neutral">{commands.length}</Badge></div>
        {commands.map((c) => <CommandRow key={c.name} cmd={c} flowId={flowId} onSend={send} />)}
      </Card>
      <Card>
        <CardHeader title={t('integration.tcp.howto')} />
        <CardBody>
          <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed">
            {(Array.isArray(howto) ? howto : []).map((l, i) => <li key={i} className="break-words">{l}</li>)}
          </ol>
          <CodeBlock title="Python socket" code={`import socket, json\n\ns = socket.create_connection(("${tcpHost}", ${info.tcp_port}), timeout=30)\ns.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)\ns.sendall(b"RUN ${flowId}\\n")\nline = b""\nwhile not line.endswith(b"\\n"):\n    line += s.recv(65536)\nprint(json.loads(line))`} />
        </CardBody>
      </Card>
    </div>
  )
}

export function TcpPage() {
  const { t } = useTranslation()
  const info = useSectionInfo()
  if (!info) return <LoadingState />
  return (
    <SectionTabs section="tcp" tabs={[
      { key: 'try', label: t('integration.sections.try'), icon: Send, content: <CommandExplorer info={info} /> },
      { key: 'codes', label: t('integration.sections.codes'), icon: ListChecks, content: <TcpCodesCard /> },
      { key: 'connections', label: t('integration.sections.connections'), icon: Plug, content: <ConnectionsSection section="tcp" /> },
      { key: 'trace', label: t('integration.trace.title'), icon: Activity, content: <TraceLog channel="tcp" /> },
    ]} />
  )
}
