/** 整合 ▸ TCP：送一行指令到 TCP 介面（POST /integration/tcp）含歷史紀錄、失敗碼對照，以及送出結果用的 TCP 連線。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Activity, ListChecks, Plug, Send } from 'lucide-react'

import { connectHost } from './shared'
import { CodeBlock, CopyButton, SectionTabs, useSectionInfo } from './shared'
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

function TcpSection({ info }: { info: IntegrationInfo }) {
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
  const tcpHost = connectHost(info.tcp_connect_host, info.tcp_host, info.host)
  const howto = t('integration.tcp.howtoLines', { returnObjects: true, host: tcpHost, port: info.tcp_port }) as unknown as string[]

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
            <span className="mr-1 text-xs text-muted">{t('integration.tcp.common')}: </span>
            {common.map((c) => (
              <button key={c} type="button" className="rounded border border-line bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] hover:border-brand" onClick={() => setCommand(c)}>{c}</button>
            ))}
          </div>
          {latest ? (
            <div className="space-y-1" data-testid="tcp-result">
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <code className="font-mono">{latest.command}</code>
                <span className="tnum">{latest.elapsed_ms} ms</span>
                <Badge tone={latest.via === 'tcp' ? 'ok' : 'warning'}>{t('integration.tcp.via')}: {latest.via}</Badge>
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
          <CodeBlock title="Python socket" code={`import socket, json\n\ns = socket.create_connection(("${tcpHost}", ${info.tcp_port}), timeout=30)\ns.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)\ns.sendall(b"RUN 1\\n")\nline = b""\nwhile not line.endswith(b"\\n"):\n    line += s.recv(65536)\nprint(json.loads(line))`} />
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
      { key: 'try', label: t('integration.sections.try'), icon: Send, content: <TcpSection info={info} /> },
      { key: 'codes', label: t('integration.sections.codes'), icon: ListChecks, content: <TcpCodesCard /> },
      { key: 'connections', label: t('integration.sections.connections'), icon: Plug, content: <ConnectionsSection section="tcp" /> },
      { key: 'trace', label: t('integration.trace.title'), icon: Activity, content: <TraceLog channel="tcp" /> },
    ]} />
  )
}
