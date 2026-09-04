/**
 * 全域 AI 助手：右下角常駐按鈕＋聊天視窗，切換頁面不會消失（對話存 localStorage）。
 * 一個輸入框依目前頁面脈絡分流：平台使用問答（文件檢索＋LLM）、流程編輯器修改流程（套用到畫布）、
 * 批次頁資料諮詢（建議套用）與依資料調整（新的一次執行）；代理模式下 edit／tune 走背景工作並顯示步驟時間軸。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bot, Check, ExternalLink, Send, Sparkles, Square, Trash2, X } from 'lucide-react'

import { AgentTimeline } from '@/components/agent/AgentTimeline'
import { Badge, Button } from '@/components/ui'
import { useAgentJob } from '@/lib/agentJob'
import { api } from '@/lib/api'
import { contextFromPath, useAssistantContext, type AssistantContext, type AssistantKind } from '@/lib/assistantContext'
import type { Suggestion, TuneResult } from '@/lib/batch'
import { errorMessage } from '@/lib/errors'
import type { FlowGraph, RunReport } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

type Mode = 'auto' | 'help' | 'edit' | 'consult' | 'tune'
type ReplyKind = 'help' | 'edit' | 'consult' | 'tune'

interface Source { title: string; page: string; heading: string; url: string; snippet: string; kind: string }
interface EditResult { graph: FlowGraph; rationale: string; provider: string; changes: string[]; report: RunReport | null; applied: boolean }
interface ChatReply {
  kind: ReplyKind
  answer: string
  provider: string
  agentic?: boolean
  sources?: Source[]
  result?: EditResult | TuneResult
  suggestions?: Suggestion[]
  warnings?: string[]
  batch_run_id?: number | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  at: number
  kind?: ReplyKind
  provider?: string
  sources?: Source[]
  edit?: { graph: FlowGraph; changes: string[]; flowId: number | null; applied?: boolean }
  suggestions?: Suggestion[]
  warnings?: string[]
  newRunId?: number | null
  contextKind?: AssistantKind
}

const STORAGE = 'vs.assistant.v1'
const MAX_MESSAGES = 60

function load(): { open: boolean; messages: ChatMessage[] } {
  try {
    const raw = localStorage.getItem(STORAGE)
    if (raw) {
      const parsed = JSON.parse(raw) as { open?: boolean; messages?: ChatMessage[] }
      return { open: Boolean(parsed.open), messages: Array.isArray(parsed.messages) ? parsed.messages.slice(-MAX_MESSAGES) : [] }
    }
  } catch { /* 無法讀取就從空的開始 */ }
  return { open: false, messages: [] }
}

function persist(open: boolean, messages: ChatMessage[]) {
  try { localStorage.setItem(STORAGE, JSON.stringify({ open, messages: messages.slice(-MAX_MESSAGES) })) } catch { /* 忽略 */ }
}

const uid = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`

export function contextPayload(ctx: AssistantContext) {
  const wantsGraph = ctx.kind === 'flow_editor' || ctx.kind === 'tool' || ctx.kind === 'batch'
  return {
    kind: ctx.kind, route: ctx.route ?? '', flow_id: ctx.flowId ?? null, flow_name: ctx.flowName ?? '', node_id: ctx.nodeId ?? '', node_type: ctx.nodeType ?? '',
    batch_run_id: ctx.batchRunId ?? null, image_ref: ctx.imageRef ?? '', graph: wantsGraph ? (ctx.getGraph?.() ?? null) : null,
  }
}

export function AssistantDock() {
  const { t } = useTranslation()
  const toast = useToast()
  const location = useLocation()
  const registered = useAssistantContext()
  const ctx = useMemo<AssistantContext>(() => registered ?? contextFromPath(location.pathname), [registered, location.pathname])
  const initial = useMemo(load, [])
  const [open, setOpen] = useState(initial.open)
  const [messages, setMessages] = useState<ChatMessage[]>(initial.messages)
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<Mode>('auto')
  const [busy, setBusy] = useState(false)
  const [unread, setUnread] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  //: 回覆常在 await 之後才到，用 ref 讀「當下」是否開著，才能正確計未讀
  const openRef = useRef(open)
  openRef.current = open
  const info = useQuery({ queryKey: ['agent-info'], queryFn: () => api.get<{ llm: boolean; provider: string; model: string; mode?: string }>('/vision/agent/info') })
  const jobs = useAgentJob<EditResult | TuneResult>()
  const agentic = Boolean(info.data?.llm && info.data?.mode === 'agentic')

  useEffect(() => { persist(open, messages) }, [open, messages])
  useEffect(() => {
    if (!open) return
    setUnread(0)
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [open, messages.length])

  function push(msg: Omit<ChatMessage, 'id' | 'at'>) {
    setMessages((list) => [...list, { ...msg, id: uid(), at: Date.now() }].slice(-MAX_MESSAGES))
    if (!openRef.current && msg.role === 'assistant') setUnread((n) => n + 1)
  }

  // 代理模式工作結束
  const jobStatus = jobs.job?.status
  const jobId = jobs.job?.id
  useEffect(() => {
    const j = jobs.job
    if (!j || j.status === 'running') return
    if ((j.status === 'done' || j.status === 'budget') && j.result) {
      const r = j.result
      if ('items' in r && 'before' in r) {
        const tr = r as TuneResult
        push({ role: 'assistant', text: tr.rationale, kind: 'tune', provider: tr.provider, warnings: tr.warnings, newRunId: tr.batch_run_id ?? null, contextKind: ctx.kind })
        if (tr.batch_run_id) ctx.onNewRun?.(tr.batch_run_id)
      } else {
        const er = r as EditResult
        push({ role: 'assistant', text: er.rationale, kind: 'edit', provider: er.provider, edit: { graph: er.graph, changes: er.changes, flowId: ctx.flowId ?? null }, contextKind: ctx.kind })
      }
    } else if (j.status === 'needs_input') {
      push({ role: 'assistant', text: t('agent.jobAnswerHint', { text: j.questions.map((q) => q.text).join('; ') }) })
    } else if (j.status === 'cancelled') push({ role: 'assistant', text: t('agent.aborted') })
    else if (j.status === 'error') push({ role: 'assistant', text: j.error || t('agent.jobStatus.error') })
    setBusy(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobStatus, jobId])

  async function send(text = input.trim()) {
    if (!text || busy) return
    setInput('')
    push({ role: 'user', text, contextKind: ctx.kind })
    setBusy(true)
    if (jobs.waiting && jobs.job) {
      try { await jobs.answer(jobs.job.questions.map((q, i) => ({ id: q.id, answer: i === 0 ? text : '' }))) } catch (error) { toast.error(errorMessage(error)); setBusy(false) }
      return
    }
    const controller = new AbortController()
    abortRef.current = controller
    const history = messages.slice(-8).map((m) => ({ role: m.role, text: m.text.slice(0, 400) }))
    try {
      const payload = contextPayload(ctx)
      const r = await api.post<ChatReply>('/vision/agent/chat', { message: text, mode, context: payload, history }, undefined, controller.signal)
      if (r.agentic && (r.kind === 'edit' || r.kind === 'tune')) {
        await jobs.start(r.kind === 'edit'
          ? { task: 'edit', graph: payload.graph, instruction: text, images: payload.image_ref ? [payload.image_ref] : [] }
          : { task: 'tune', batch_run_id: payload.batch_run_id, instruction: text, graph: payload.graph })
        return
      }
      if (r.kind === 'edit' && r.result) {
        const er = r.result as EditResult
        push({ role: 'assistant', text: r.answer, kind: 'edit', provider: r.provider, edit: er.applied ? { graph: er.graph, changes: er.changes, flowId: ctx.flowId ?? null } : undefined, contextKind: ctx.kind })
      } else if (r.kind === 'tune') {
        push({ role: 'assistant', text: r.answer, kind: 'tune', provider: r.provider, warnings: r.warnings, newRunId: r.batch_run_id ?? null, contextKind: ctx.kind })
        if (r.batch_run_id) ctx.onNewRun?.(r.batch_run_id)
      } else if (r.kind === 'consult') {
        push({ role: 'assistant', text: r.answer, kind: 'consult', provider: r.provider, suggestions: r.suggestions, warnings: r.warnings, contextKind: ctx.kind })
      } else {
        push({ role: 'assistant', text: r.answer, kind: 'help', provider: r.provider, sources: r.sources, warnings: r.warnings, contextKind: ctx.kind })
      }
    } catch (error) {
      if (controller.signal.aborted) push({ role: 'assistant', text: t('agent.aborted') })
      else push({ role: 'assistant', text: errorMessage(error) })
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setBusy(false)
    }
  }

  function abort() {
    if (jobs.running) void jobs.cancel()
    else abortRef.current?.abort()
  }

  function applyEdit(m: ChatMessage) {
    if (!m.edit) return
    if (!ctx.applyGraph || (m.edit.flowId !== null && ctx.flowId !== m.edit.flowId)) {
      toast.warning(t('assistant.applyNeedsEditor'))
      return
    }
    ctx.applyGraph(m.edit.graph, m.text)
    setMessages((list) => list.map((x) => (x.id === m.id && x.edit ? { ...x, edit: { ...x.edit, applied: true } } : x)))
  }

  const modes: Mode[] = ['auto', 'help', ...(ctx.kind === 'flow_editor' || ctx.kind === 'tool' ? ['edit' as const] : []), ...(ctx.kind === 'batch' && ctx.batchRunId ? ['consult' as const, 'tune' as const] : [])]
  const quick = (t(`assistant.quick.${ctx.kind}`, { returnObjects: true, defaultValue: [] }) as string[] | string)
  const quickList = Array.isArray(quick) ? quick : (t('assistant.quick.page', { returnObjects: true }) as string[])
  const ctxLabel = `${t(`assistant.ctx.${ctx.kind}`)}${ctx.flowName ? ` · ${ctx.flowName}` : ''}${ctx.nodeType ? ` · ${ctx.nodeType}` : ''}${ctx.batchRunId ? ` · #${ctx.batchRunId}` : ''}`

  return (
    <>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-label={t('assistant.title')} title={t('assistant.title')} data-testid="assistant-toggle"
        className="fixed bottom-4 right-4 z-40 flex size-12 items-center justify-center rounded-full bg-brand text-white shadow-lg transition hover:brightness-110">
        {open ? <X size={20} /> : <Bot size={22} />}
        {!open && unread > 0 ? <span className="absolute -right-0.5 -top-0.5 flex size-5 items-center justify-center rounded-full bg-critical text-[10px] font-bold text-white">{unread}</span> : null}
      </button>
      {open ? (
        <section className="fixed bottom-20 right-4 z-40 flex h-[min(72vh,720px)] w-[min(420px,calc(100vw-2rem))] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-2xl" data-testid="assistant-dock" aria-label={t('assistant.title')}>
          <header className="flex items-center gap-2 border-b border-line px-3 py-2">
            <Sparkles size={14} className="text-brand" />
            <span className="shrink-0 whitespace-nowrap text-sm font-semibold">{t('assistant.title')}</span>
            {info.data ? <Badge tone={info.data.llm ? 'brand' : 'neutral'} className="max-w-[55%] truncate">{info.data.llm ? `${info.data.model}${agentic ? ` · ${t('assistant.agentic')}` : ''}` : t('agent.providerRules')}</Badge> : null}
            <span className="ml-auto flex items-center gap-0.5">
              <button type="button" className="btn-icon" title={t('assistant.clear')} onClick={() => setMessages([])} data-testid="assistant-clear"><Trash2 size={14} /></button>
              <button type="button" className="btn-icon" title={t('common.close')} onClick={() => setOpen(false)}><X size={15} /></button>
            </span>
          </header>
          <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-1.5 text-[11px]">
            <Badge tone="info">{ctxLabel}</Badge>
            <span className="ml-auto flex gap-1">
              {modes.map((m) => (
                <button key={m} type="button" onClick={() => setMode(m)} className={`rounded-full border px-2 py-0.5 ${mode === m ? 'border-brand bg-brand-soft text-brand' : 'border-line text-muted hover:bg-surface-muted'}`} data-testid={`assistant-mode-${m}`}>{t(`assistant.mode.${m}`)}</button>
              ))}
            </span>
          </div>
          <div ref={listRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3 text-xs" data-testid="assistant-messages">
            {messages.length === 0 ? (
              <div className="space-y-2">
                <p className="text-muted">{t('assistant.empty')}</p>
                <p className="text-[11px] text-subtle">{t(`assistant.hint.${ctx.kind}`, { defaultValue: t('assistant.hint.page') })}</p>
              </div>
            ) : null}
            {messages.map((m) => (
              <div key={m.id} className={`rounded-lg px-2.5 py-2 ${m.role === 'user' ? 'ml-8 bg-brand-soft' : 'mr-4 bg-surface-muted'}`} data-testid={`assistant-msg-${m.role}`}>
                <p className="whitespace-pre-wrap leading-relaxed">{m.text}</p>
                {m.provider ? <p className="mt-1 text-[10px] text-subtle">{m.provider}{m.kind ? ` · ${t(`assistant.mode.${m.kind}`)}` : ''}</p> : null}
                {m.warnings?.length ? <ul className="mt-1 list-disc pl-4 text-[11px] text-warning">{m.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul> : null}
                {m.sources?.length ? (
                  <ul className="mt-1.5 space-y-0.5 border-t border-line pt-1.5 text-[11px]">
                    <li className="font-semibold text-muted">{t('assistant.sources')}</li>
                    {m.sources.slice(0, 4).map((s) => (
                      <li key={s.url + s.heading}><a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand hover:underline">{s.title}<ExternalLink size={10} /></a></li>
                    ))}
                  </ul>
                ) : null}
                {m.edit ? (
                  <div className="mt-1.5 space-y-1">
                    {m.edit.changes.length ? <ul className="list-disc pl-4 text-[11px] text-muted">{m.edit.changes.map((c, i) => <li key={i}>{c}</li>)}</ul> : null}
                    {m.edit.applied ? <Badge tone="ok">{t('agent.applied')}</Badge> : <Button size="xs" variant="primary" icon={<Check size={12} />} onClick={() => applyEdit(m)} data-testid="assistant-apply">{t('agent.apply')}</Button>}
                  </div>
                ) : null}
                {m.suggestions?.length ? (
                  <div className="mt-1.5 space-y-1">
                    {m.suggestions.map((s, i) => (
                      <p key={i} className="flex items-center gap-2 text-[11px]"><span className="font-mono">{s.label}.{s.key} → {String(s.value)}</span>
                        {ctx.applySuggestions ? <Button size="xs" onClick={() => ctx.applySuggestions?.([s])}>{t('batchPage.ai.apply')}</Button> : null}</p>
                    ))}
                  </div>
                ) : null}
                {m.newRunId ? <p className="mt-1 text-[11px] text-brand">{t('batchPage.ai.newRun', { id: m.newRunId })}</p> : null}
              </div>
            ))}
            {jobs.job && (jobs.running || jobs.waiting) ? <AgentTimeline job={jobs.job} steps={jobs.steps} onCancel={abort} /> : null}
            {busy && !jobs.running ? <p className="text-subtle">{t('assistant.thinking')}</p> : null}
          </div>
          {messages.length === 0 && quickList.length ? (
            <div className="flex flex-wrap gap-1 border-t border-line px-3 py-1.5">
              {quickList.map((q) => <button key={q} type="button" disabled={busy} onClick={() => void send(q)} className="rounded-full border border-line px-2 py-0.5 text-[11px] text-muted hover:bg-surface-muted" data-testid="assistant-quick">{q}</button>)}
            </div>
          ) : null}
          <div className="flex gap-1.5 border-t border-line p-2">
            <input className="input flex-1 !py-1.5 text-xs" placeholder={t('assistant.placeholder')} value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) void send() }} disabled={busy && !jobs.waiting} data-testid="assistant-input" />
            {busy ? <Button size="sm" variant="danger" icon={<Square size={13} />} onClick={abort} data-testid="assistant-abort">{t('agent.abort')}</Button>
              : <Button size="sm" variant="primary" icon={<Send size={13} />} disabled={!input.trim()} onClick={() => void send()} data-testid="assistant-send">{t('assistant.send')}</Button>}
          </div>
        </section>
      ) : null}
    </>
  )
}
