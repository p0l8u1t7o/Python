/**
 * 全域 AI 助手：右下角常駐按鈕＋聊天視窗，切換頁面不會消失（對話存 localStorage）。
 * 一個輸入框依目前頁面脈絡分流：平台使用問答（文件檢索＋LLM）、流程編輯器修改流程（套用到畫布）、
 * 批次頁資料諮詢（建議套用）與依資料調整（新的一次執行）；代理模式下 edit／tune 走背景工作並顯示步驟時間軸。
 */
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Bot, Brain, Camera, Check, ExternalLink, Eye, EyeOff, History, Lightbulb, Monitor, MonitorOff, Plus, Send, Sparkles, Square, ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react'

import { AgentTimeline } from '@/components/agent/AgentTimeline'
import { TaskListCard } from './TaskListCard'
import { Badge, Button } from '@/components/ui'
import { useAgentJob } from '@/lib/agentJob'
import { activityPayload, logActivity, recentActivity, setActivityRoute, setShareEnabled, shareEnabled, subscribeActivity } from '@/lib/activity'
import { api } from '@/lib/api'
import { contextFromPath, useAssistantContext, type AssistantContext, type AssistantKind } from '@/lib/assistantContext'
import type { Suggestion, TuneResult } from '@/lib/batch'
import { errorMessage } from '@/lib/errors'
import { formatDateTime } from '@/lib/format'
import i18n from '@/i18n'
import { dismissHint, hintFor, shouldShow, type Hint } from '@/lib/hints'
import { pageSnapshot, screenSummary, setIntegrationTab } from '@/lib/screen'
import { base64Of, captureScreenshot } from '@/lib/screenshot'
import { sectionOf } from '@/pages/integration/sections'
import type { FlowGraph, InspectKind, RunReport, TaskDraft } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

type Mode = 'auto' | 'help' | 'edit' | 'consult' | 'tune'
type ReplyKind = 'help' | 'edit' | 'consult' | 'tune' | 'tasklist'

interface Source { title: string; page: string; heading: string; url: string; snippet: string; kind: string }
/** 回覆附的捷徑：前往頁面（可指定分頁）、在編輯器聚焦節點、開該節點的工具頁。 */
export type AssistantAction =
  | { kind: 'navigate'; to: string; tab?: string; label: string }
  | { kind: 'focus_node' | 'open_tool'; node: string; flow_id: number; label: string }
interface Lookup { name: string; args: Record<string, unknown>; error?: string }
/** 長期記憶的一筆：fact＝使用者要它記住的一句話；qa＝問過的問答（可評分）。 */
interface MemoryItem { id: number; kind: 'fact' | 'qa'; text: string; answer: string; rating: number; created_at: string | null }
interface MemoryList { facts: MemoryItem[]; qa: MemoryItem[]; limits: { facts: number; qa: number } }
/** 過去的對話（伺服器存，每位使用者自己的） */
interface ChatSummary { id: number; title: string; count: number; updated_at: string | null }
interface EditResult { graph: FlowGraph; rationale: string; provider: string; changes: string[]; report: RunReport | null; applied: boolean }
interface ChatReply {
  drafts?: TaskDraft[]
  kinds?: InspectKind[]
  kind: ReplyKind
  answer: string
  provider: string
  agentic?: boolean
  sources?: Source[]
  result?: EditResult | TuneResult
  suggestions?: Suggestion[]
  warnings?: string[]
  batch_run_id?: number | null
  actions?: AssistantAction[]
  lookups?: Lookup[]
  memory_id?: number
}

export interface ChatMessage {
  tasklist?: { drafts: TaskDraft[]; flowId: number | null; kinds?: InspectKind[] }
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
  actions?: AssistantAction[]
  lookups?: Lookup[]
  /** 後端留的問答記憶 id（可評分） */
  memoryId?: number
  rating?: number
}

const STORAGE = 'vs.assistant.v1'
const MAX_MESSAGES = 60

function load(): { open: boolean; messages: ChatMessage[]; sessionId: number | null } {
  try {
    const raw = localStorage.getItem(STORAGE)
    if (raw) {
      const parsed = JSON.parse(raw) as { open?: boolean; messages?: ChatMessage[]; sessionId?: number | null }
      return {
        open: Boolean(parsed.open),
        messages: Array.isArray(parsed.messages) ? parsed.messages.slice(-MAX_MESSAGES) : [],
        sessionId: typeof parsed.sessionId === 'number' ? parsed.sessionId : null,
      }
    }
  } catch { /* 無法讀取就從空的開始 */ }
  return { open: false, messages: [], sessionId: null }
}

function persist(open: boolean, messages: ChatMessage[], sessionId: number | null) {
  try { localStorage.setItem(STORAGE, JSON.stringify({ open, messages: messages.slice(-MAX_MESSAGES), sessionId })) } catch { /* 忽略 */ }
}

const uid = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`

export function contextPayload(ctx: AssistantContext, pathname = ctx.route ?? '') {
  const wantsGraph = ctx.kind === 'inspect' || ctx.kind === 'flow_editor' || ctx.kind === 'tool' || ctx.kind === 'batch'
  // 分享關閉時只送頁面種類與流程／節點識別，不送畫面快照與操作軌跡
  const share = shareEnabled()
  const page = share ? { ...pageSnapshot(pathname), ...(ctx.describe?.() ?? {}) } : null
  return {
    kind: ctx.kind, route: pathname || (ctx.route ?? ''), flow_id: ctx.flowId ?? null, flow_name: ctx.flowName ?? '', node_id: ctx.nodeId ?? '', node_type: ctx.nodeType ?? '',
    batch_run_id: ctx.batchRunId ?? null, image_ref: ctx.imageRef ?? '', graph: wantsGraph ? (ctx.getGraph?.() ?? null) : null,
    lang: i18n.language, page: page && Object.keys(page).length ? page : null, activity: share ? activityPayload() : [],
  }
}

export function AssistantDock() {
  const { t } = useTranslation()
  const toast = useToast()
  const location = useLocation()
  const navigate = useNavigate()
  const registered = useAssistantContext()
  const ctx = useMemo<AssistantContext>(() => registered ?? contextFromPath(location.pathname), [registered, location.pathname])
  const initial = useMemo(load, [])
  const [open, setOpen] = useState(initial.open)
  const [messages, setMessages] = useState<ChatMessage[]>(initial.messages)
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<Mode>('auto')
  const [busy, setBusy] = useState(false)
  const [unread, setUnread] = useState(0)
  const share = useSyncExternalStore(subscribeActivity, shareEnabled, shareEnabled)
  //: 主動提示：軌跡出現認得的失敗就配一句提示與一個可直接送出的問題（同種 5 分鐘一次、關掉就不再出現）
  const [hint, setHint] = useState<Hint | null>(null)
  //: 附上畫面：開著時每次提問帶目前畫面的文字摘要（只有分享開著才會送）
  const [attachScreen, setAttachScreen] = useState(false)
  //: 截圖：按相機擷取一張、附在下一則提問（送出後清掉）
  const [shot, setShot] = useState<string | null>(null)
  const [shotBusy, setShotBusy] = useState(false)
  //: 記憶面板（事實與最近問答）
  const [showMemory, setShowMemory] = useState(false)
  //: 對話：目前這條的 id（伺服器）＋過去對話面板
  const auth = useAuth()
  const canStore = auth.me?.kind === 'user'
  const [sessionId, setSessionId] = useState<number | null>(initial.sessionId)
  const [showHistory, setShowHistory] = useState(false)
  const [memoryInput, setMemoryInput] = useState('')
  const queryClient = useQueryClient()
  const memory = useQuery({ queryKey: ['assistant-memory'], queryFn: () => api.get<MemoryList>('/vision/agent/memory'), enabled: showMemory })
  const chatList = useQuery({
    queryKey: ['assistant-chats'],
    queryFn: () => api.get<{ items: ChatSummary[] }>('/vision/agent/chats'),
    enabled: canStore && showHistory,
  })
  const removeChat = useMutation({
    mutationFn: (id: number) => api.delete(`/vision/agent/chats/${id}`),
    onSuccess: (_data, id) => {
      if (id === sessionId) { setMessages([]); setSessionId(null) }
      void queryClient.invalidateQueries({ queryKey: ['assistant-chats'] })
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
  const addMemory = useMutation({
    mutationFn: (text: string) => api.post<MemoryItem>('/vision/agent/memory', { text }),
    onSuccess: () => { setMemoryInput(''); toast.success(t('assistant.memory.added')); void queryClient.invalidateQueries({ queryKey: ['assistant-memory'] }) },
    onError: (error) => toast.error(errorMessage(error)),
  })
  const deleteMemory = useMutation({
    mutationFn: (id: number) => api.delete(`/vision/agent/memory/${id}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['assistant-memory'] }),
    onError: (error) => toast.error(errorMessage(error)),
  })
  useEffect(() => subscribeActivity(() => {
    const last = recentActivity(1)[0]
    const h = last ? hintFor(last) : null
    if (h && shouldShow(h)) {
      setHint(h)
      if (!openRef.current) setUnread((n) => n + 1)
    }
  }), [])
  //: 換頁記進操作軌跡（助手回答「剛剛」的依據）
  useEffect(() => {
    setActivityRoute(location.pathname)
    logActivity('nav', location.pathname)
  }, [location.pathname])
  const abortRef = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  //: 回覆常在 await 之後才到，用 ref 讀「當下」是否開著，才能正確計未讀
  const openRef = useRef(open)
  openRef.current = open
  const info = useQuery({ queryKey: ['agent-info'], queryFn: () => api.get<{ llm: boolean; provider: string; model: string; mode?: string }>('/vision/agent/info') })
  const jobs = useAgentJob<EditResult | TuneResult>()
  const agentic = Boolean(info.data?.llm && info.data?.mode === 'agentic')

  useEffect(() => { persist(open, messages, sessionId) }, [open, messages, sessionId])
  //: 訊息變了就寫回伺服器（延遲 1 秒批次寫；沒有對話就先開一條）。失敗不打擾使用者——本機還留著。
  const savingRef = useRef(false)
  useEffect(() => {
    if (!canStore || messages.length === 0) return
    const timer = window.setTimeout(async () => {
      if (savingRef.current) return
      savingRef.current = true
      try {
        const body = { messages: messages.slice(-MAX_MESSAGES) }
        if (sessionId === null) {
          const row = await api.post<ChatSummary>('/vision/agent/chats', body)
          setSessionId(row.id)
        } else {
          await api.patch(`/vision/agent/chats/${sessionId}`, body)
        }
        void queryClient.invalidateQueries({ queryKey: ['assistant-chats'] })
      } catch {
        /* 對話存檔失敗（離線、權限）：不擋使用，下一則再試 */
      } finally {
        savingRef.current = false
      }
    }, 1000)
    return () => window.clearTimeout(timer)
  }, [messages, canStore, sessionId, queryClient])

  /** 開新對話：目前這條已經在伺服器上，直接清空畫面即可。 */
  function newSession() {
    setMessages([])
    setSessionId(null)
    setShowHistory(false)
    setShowMemory(false)
    setHint(null)
  }

  /** 回到過去的對話：把訊息整條載回來（來源、建議、動作都還原）。 */
  async function openSession(id: number) {
    try {
      const row = await api.get<{ id: number; messages: ChatMessage[] }>(`/vision/agent/chats/${id}`)
      setMessages(Array.isArray(row.messages) ? row.messages : [])
      setSessionId(row.id)
      setShowHistory(false)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
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
      const payload = { ...contextPayload(ctx, location.pathname), screen: attachScreen && share ? screenSummary() : '', screenshot: shot ? base64Of(shot) : '' }
      setShot(null)
      const r = await api.post<ChatReply>('/vision/agent/chat', { message: text, mode, context: payload, history }, undefined, controller.signal)
      if (r.agentic && (r.kind === 'edit' || r.kind === 'tune')) {
        await jobs.start(r.kind === 'edit'
          ? { task: 'edit', graph: payload.graph, instruction: text, images: payload.image_ref ? [payload.image_ref] : [] }
          : { task: 'tune', batch_run_id: payload.batch_run_id, instruction: text, graph: payload.graph })
        return
      }
      if (r.kind === 'tasklist') {
        push({ role: 'assistant', text: r.answer || '', kind: 'tasklist', warnings: r.warnings, tasklist: { drafts: r.drafts ?? [], kinds: r.kinds, flowId: ctx.flowId ?? null }, contextKind: ctx.kind })
      } else if (r.kind === 'edit' && r.result) {
        const er = r.result as EditResult
        push({ role: 'assistant', text: r.answer, kind: 'edit', provider: r.provider, edit: er.applied ? { graph: er.graph, changes: er.changes, flowId: ctx.flowId ?? null } : undefined, contextKind: ctx.kind })
      } else if (r.kind === 'tune') {
        push({ role: 'assistant', text: r.answer, kind: 'tune', provider: r.provider, warnings: r.warnings, newRunId: r.batch_run_id ?? null, contextKind: ctx.kind })
        if (r.batch_run_id) ctx.onNewRun?.(r.batch_run_id)
      } else if (r.kind === 'consult') {
        push({ role: 'assistant', text: r.answer, kind: 'consult', provider: r.provider, suggestions: r.suggestions, warnings: r.warnings, contextKind: ctx.kind })
      } else {
        push({ role: 'assistant', text: r.answer, kind: 'help', provider: r.provider, sources: r.sources, warnings: r.warnings, contextKind: ctx.kind, actions: r.actions, lookups: r.lookups, memoryId: r.memory_id })
        if (r.provider === 'memory') void queryClient.invalidateQueries({ queryKey: ['assistant-memory'] })
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

  const proposalIds = messages.flatMap((m) => m.tasklist && m.tasklist.flowId === ctx.flowId ? m.tasklist.drafts.filter((d) => d.task_id && Object.values(d.fields).some((v) => v.status === 'assumed')).map((d) => d.task_id!) : []).join('|')
  useEffect(() => {
    ctx.proposalTasks?.(proposalIds ? proposalIds.split('|') : [])
  }, [ctx.proposalTasks, proposalIds])

  async function takeShot() {
    setShotBusy(true)
    try {
      const url = await captureScreenshot()
      if (url) setShot(url)
      else toast.warning(t('assistant.screenshotFailed'))
    } finally {
      setShotBusy(false)
    }
  }

  /** 評分一則回答：好的會在相似問題時被重用。 */
  async function rate(m: ChatMessage, rating: number) {
    if (!m.memoryId) return
    try {
      await api.post(`/vision/agent/memory/${m.memoryId}/rate`, { rating })
      setMessages((list) => list.map((x) => (x.id === m.id ? { ...x, rating } : x)))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  /** 回覆的捷徑：整合頁先記住要開的分頁再導頁；節點動作只在同一條流程的編輯器內有效。 */
  function runAction(a: AssistantAction) {
    if (a.kind === 'navigate') {
      if (a.tab && a.to.startsWith('/integration/')) setIntegrationTab(sectionOf(a.to), a.tab)
      navigate(a.to)
      return
    }
    if (a.kind === 'focus_node' && ctx.focusNode && ctx.flowId === a.flow_id) {
      ctx.focusNode(a.node)
      return
    }
    navigate(a.kind === 'open_tool' ? `/flows/${a.flow_id}/tools/${a.node}` : `/flows/${a.flow_id}`)
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
  const ctxLabel = `${t(ctx.kind === 'inspect' ? 'assistant.tasklist.context' : `assistant.ctx.${ctx.kind}`)}${ctx.flowName ? ` · ${ctx.flowName}` : ''}${ctx.nodeType ? ` · ${ctx.nodeType}` : ''}${ctx.batchRunId ? ` · #${ctx.batchRunId}` : ''}`

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
              <button type="button" className={`btn-icon ${showMemory ? 'text-brand' : ''}`} title={t('assistant.memory.open')} aria-pressed={showMemory} onClick={() => { setShowMemory((v) => !v); setShowHistory(false) }} data-testid="assistant-memory-toggle"><Brain size={14} /></button>
              <button type="button" className={`btn-icon ${shot ? 'text-brand' : ''}`} title={!info.data?.llm ? t('assistant.screenshotNeedsLlm') : t('assistant.screenshot')} disabled={!info.data?.llm || !share || shotBusy} onClick={() => void takeShot()} data-testid="assistant-shot"><Camera size={14} /></button>
              <button type="button" className={`btn-icon ${attachScreen ? 'text-brand' : ''}`} title={attachScreen ? t('assistant.attachScreenOn') : t('assistant.attachScreen')} aria-pressed={attachScreen} disabled={!share} onClick={() => setAttachScreen((v) => !v)} data-testid="assistant-screen">{attachScreen ? <Monitor size={14} /> : <MonitorOff size={14} />}</button>
              <button type="button" className={`btn-icon ${share ? '' : 'text-warning'}`} title={share ? t('assistant.shareOn') : t('assistant.shareOff')} aria-pressed={share} onClick={() => setShareEnabled(!share)} data-testid="assistant-share">{share ? <Eye size={14} /> : <EyeOff size={14} />}</button>
              {canStore ? (
                <button type="button" className={`btn-icon ${showHistory ? 'text-brand' : ''}`} title={t('assistant.sessions.history')} aria-pressed={showHistory}
                  onClick={() => { setShowHistory((v) => !v); setShowMemory(false) }} data-testid="assistant-history-toggle"><History size={14} /></button>
              ) : null}
              <button type="button" className="btn-icon" title={t('assistant.sessions.new')} onClick={newSession} data-testid="assistant-new-session"><Plus size={15} /></button>
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
          {showHistory ? (
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3 text-xs" data-testid="assistant-history">
              <div className="flex items-center gap-2">
                <p className="flex-1 text-[11px] text-muted">{t('assistant.sessions.hint')}</p>
                <Button size="xs" variant="primary" onClick={newSession} data-testid="assistant-history-new">{t('assistant.sessions.new')}</Button>
              </div>
              {chatList.isPending ? <p className="text-subtle">{t('common.loading')}</p> : null}
              {chatList.data && chatList.data.items.length === 0 ? <p className="text-subtle" data-testid="assistant-history-empty">{t('assistant.sessions.empty')}</p> : null}
              <ul className="space-y-1">
                {(chatList.data?.items ?? []).map((c) => (
                  <li key={c.id} className={`flex items-start gap-2 rounded-md px-2 py-1 ${c.id === sessionId ? 'bg-brand-soft' : 'bg-surface-muted'}`} data-testid="assistant-session">
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => void openSession(c.id)} data-testid="assistant-session-open">
                      <span className="block truncate">{c.title || t('assistant.sessions.untitled')}</span>
                      <span className="block text-[10px] text-subtle">{t('assistant.sessions.count', { count: c.count })}{c.updated_at ? ` · ${formatDateTime(c.updated_at)}` : ''}</span>
                    </button>
                    <button type="button" className="btn-icon shrink-0" title={t('assistant.sessions.delete')} aria-label={t('assistant.sessions.delete')}
                      onClick={() => removeChat.mutate(c.id)} data-testid="assistant-session-delete"><Trash2 size={12} /></button>
                  </li>
                ))}
              </ul>
            </div>
          ) : showMemory ? (
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 text-xs" data-testid="assistant-memory">
              <p className="text-[11px] text-muted">{t('assistant.memory.hint')}</p>
              <div className="flex gap-1.5">
                <input className="input flex-1 !py-1 text-xs" placeholder={t('assistant.memory.placeholder')} value={memoryInput} onChange={(e) => setMemoryInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && memoryInput.trim()) addMemory.mutate(memoryInput.trim()) }} data-testid="assistant-memory-input" />
                <Button size="sm" variant="primary" disabled={!memoryInput.trim() || addMemory.isPending} onClick={() => addMemory.mutate(memoryInput.trim())} data-testid="assistant-memory-add">{t('assistant.memory.add')}</Button>
              </div>
              <section>
                <p className="mb-1 font-semibold text-muted">{t('assistant.memory.facts')}{memory.data ? ` (${memory.data.facts.length}/${memory.data.limits.facts})` : ''}</p>
                {memory.data && memory.data.facts.length === 0 ? <p className="text-subtle">{t('assistant.memory.empty')}</p> : null}
                <ul className="space-y-1">
                  {(memory.data?.facts ?? []).map((f) => (
                    <li key={f.id} className="flex items-start gap-2 rounded-md bg-surface-muted px-2 py-1" data-testid="assistant-memory-fact">
                      <span className="flex-1 break-words">{f.text}</span>
                      <button type="button" className="btn-icon shrink-0" title={t('assistant.memory.delete')} aria-label={t('assistant.memory.delete')} onClick={() => deleteMemory.mutate(f.id)}><Trash2 size={12} /></button>
                    </li>
                  ))}
                </ul>
              </section>
              <section>
                <p className="mb-1 font-semibold text-muted">{t('assistant.memory.qa')}</p>
                <ul className="space-y-1">
                  {(memory.data?.qa ?? []).slice(0, 15).map((q) => (
                    <li key={q.id} className="flex items-start gap-2 rounded-md bg-surface-muted px-2 py-1" data-testid="assistant-memory-qa">
                      <span className="flex-1 truncate" title={q.answer}>{q.text}</span>
                      {q.rating > 0 ? <ThumbsUp size={11} className="shrink-0 text-ok" /> : q.rating < 0 ? <ThumbsDown size={11} className="shrink-0 text-critical" /> : null}
                      <button type="button" className="btn-icon shrink-0" title={t('assistant.memory.delete')} aria-label={t('assistant.memory.delete')} onClick={() => deleteMemory.mutate(q.id)}><Trash2 size={12} /></button>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          ) : (
          <div ref={listRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3 text-xs" data-testid="assistant-messages">
            {hint ? (
              <div className="rounded-lg border border-warning/40 bg-warning-soft px-2.5 py-2 text-[11px]" data-testid="assistant-hint">
                <p className="flex items-center gap-1 font-semibold text-warning"><Lightbulb size={12} /> {t('assistant.hintTitle')}</p>
                <p className="mt-0.5">{t(`assistant.hints.${hint.key}`)}</p>
                <p className="mt-0.5 truncate text-subtle" title={hint.detail}>{hint.detail}</p>
                <div className="mt-1 flex gap-1">
                  <Button size="xs" variant="primary" disabled={busy} onClick={() => { const q = hint.question; setHint(null); void send(q) }} data-testid="assistant-hint-ask">{t('assistant.hintAsk')}</Button>
                  <Button size="xs" onClick={() => { dismissHint(hint.key); setHint(null) }} data-testid="assistant-hint-dismiss">{t('assistant.hintDismiss')}</Button>
                </div>
              </div>
            ) : null}
            {messages.length === 0 ? (
              <div className="space-y-2">
                <p className="text-muted">{t('assistant.empty')}</p>
                <p className="text-[11px] text-subtle">{t(`assistant.hint.${ctx.kind}`, { defaultValue: t('assistant.hint.page') })}</p>
                <p className="text-[11px] text-subtle">{t('assistant.memory.hint')}</p>
              </div>
            ) : null}
            {messages.map((m) => (
              <div key={m.id} className={`rounded-lg px-2.5 py-2 ${m.role === 'user' ? 'ml-8 bg-brand-soft' : 'mr-4 bg-surface-muted'}`} data-testid={`assistant-msg-${m.role}`}>
                <p className="whitespace-pre-wrap leading-relaxed">{m.text}</p>
                {m.tasklist?.drafts.length ? <TaskListCard drafts={m.tasklist.drafts} kinds={m.tasklist.kinds} flowId={m.tasklist.flowId} context={ctx} onChange={(drafts) => setMessages((list) => list.map((entry) => entry.id === m.id ? { ...entry, tasklist: { ...m.tasklist!, drafts } } : entry))} /> : null}
                {m.provider ? <p className="mt-1 text-[10px] text-subtle">{m.provider}{m.kind ? ` · ${t(`assistant.mode.${m.kind}`)}` : ''}</p> : null}
                {m.warnings?.length ? <ul className="mt-1 list-disc pl-4 text-[11px] text-warning">{m.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul> : null}
                {m.sources?.length ? (
                  <ul className="mt-1.5 space-y-0.5 border-t border-line pt-1.5 text-[11px]">
                    <li className="font-semibold text-muted">{t('assistant.sources')}</li>
                    {m.sources.slice(0, 4).map((s) => (
                      <li key={s.url + s.heading}>
                        {s.kind === 'ui' || s.url.startsWith('/help/')
                          ? <Link to={s.url} className="inline-flex items-center gap-1 text-brand hover:underline" data-testid={s.kind === 'ui' ? 'assistant-ui-link' : 'assistant-guide-link'}>{s.title}</Link>
                          : <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand hover:underline">{s.title}<ExternalLink size={10} /></a>}
                      </li>
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
                {m.actions?.length ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {m.actions.map((a, i) => <Button key={i} size="xs" icon={<ArrowRight size={12} />} onClick={() => runAction(a)} data-testid="assistant-action">{a.label}</Button>)}
                  </div>
                ) : null}
                {m.lookups?.length ? (
                  <p className="mt-1 text-[10px] text-subtle" data-testid="assistant-lookups">{t('assistant.checked')}: {m.lookups.map((l) => (l.error ? `${l.name} (${t('assistant.lookupDenied')})` : l.name)).join(', ')}</p>
                ) : null}
                {m.memoryId && m.kind === 'help' ? (
                  <p className="mt-1 flex items-center gap-1 text-[10px] text-subtle">
                    {m.rating ? <span>{t('assistant.rated')}</span> : null}
                    <button type="button" className={`btn-icon !size-6 ${m.rating === 1 ? 'text-ok' : ''}`} title={t('assistant.rateUp')} aria-label={t('assistant.rateUp')} onClick={() => void rate(m, m.rating === 1 ? 0 : 1)} data-testid="assistant-rate-up"><ThumbsUp size={11} /></button>
                    <button type="button" className={`btn-icon !size-6 ${m.rating === -1 ? 'text-critical' : ''}`} title={t('assistant.rateDown')} aria-label={t('assistant.rateDown')} onClick={() => void rate(m, m.rating === -1 ? 0 : -1)} data-testid="assistant-rate-down"><ThumbsDown size={11} /></button>
                  </p>
                ) : null}
              </div>
            ))}
            {jobs.job && (jobs.running || jobs.waiting) ? <AgentTimeline job={jobs.job} steps={jobs.steps} onCancel={abort} /> : null}
            {busy && !jobs.running ? <p className="text-subtle">{t('assistant.thinking')}</p> : null}
          </div>
          )}
          {shot ? (
            <div className="flex items-center gap-2 border-t border-line px-3 py-1.5 text-[11px]" data-testid="assistant-shot-chip">
              <img src={shot} alt="" className="h-8 w-auto rounded border border-line" />
              <span className="flex-1 text-muted">{t('assistant.screenshotTaken')}</span>
              <button type="button" className="btn-icon" title={t('assistant.screenshotRemove')} aria-label={t('assistant.screenshotRemove')} onClick={() => setShot(null)} data-testid="assistant-shot-remove"><X size={12} /></button>
            </div>
          ) : null}
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
