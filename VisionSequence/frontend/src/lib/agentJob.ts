/**
 * AI 助手背景工作（代理模式）：POST /vision/agent/jobs 建立 → 每秒輪詢 GET /jobs/{id}?step_from= 取新步驟 →
 * done／budget 取 result；needs_input 等使用者回答（POST /answer 後續跑）；cancel 取消。
 * 三個入口（AI 助手頁、編輯器 AI 分頁、批次測試「請 AI 調整」）共用這個 hook 與 AgentTimeline。
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '@/lib/api'

export interface AgentStep {
  n: number
  /** tool | error | assistant | question | answer | done | budget | info */
  kind: string
  title: string
  detail: string
  at: number
  ms?: number
  turn?: number
}

export interface AgentQuestion {
  id: string
  text: string
  kind: 'choice' | 'number' | 'text' | 'roi'
  optional?: boolean
  hint?: string
  options?: { value: string; label: string }[]
}

export type AgentJobStatus = 'running' | 'done' | 'needs_input' | 'budget' | 'cancelled' | 'error'

export interface AgentJob<T = unknown> {
  id: string
  task: string
  status: AgentJobStatus
  provider: string
  model: string
  mode: string
  turns: number
  trials: number
  tool_calls: number
  budget: { max_turns: number; max_trials: number; max_tool_calls: number; deadline_s: number }
  steps: AgentStep[]
  step_next: number
  questions: AgentQuestion[]
  result: T | null
  error: string
  fallback_reason: string
  duration_s: number
}

export const TERMINAL: ReadonlySet<AgentJobStatus> = new Set<AgentJobStatus>(['done', 'budget', 'cancelled', 'error'])
const POLL_MS = 1000

export function useAgentJob<T>() {
  const [job, setJob] = useState<AgentJob<T> | null>(null)
  const [steps, setSteps] = useState<AgentStep[]>([])
  const stepsRef = useRef<AgentStep[]>([])
  const timer = useRef<number | null>(null)

  const stop = useCallback(() => {
    if (timer.current !== null) {
      window.clearInterval(timer.current)
      timer.current = null
    }
  }, [])

  const apply = useCallback((j: AgentJob<T>) => {
    if (j.steps?.length) {
      stepsRef.current = [...stepsRef.current, ...j.steps]
      setSteps(stepsRef.current)
    }
    setJob({ ...j, steps: stepsRef.current })
    if (TERMINAL.has(j.status) || j.status === 'needs_input') stop()
  }, [stop])

  const schedule = useCallback((id: string) => {
    stop()
    timer.current = window.setInterval(async () => {
      try {
        const j = await api.get<AgentJob<T>>(`/vision/agent/jobs/${id}?step_from=${stepsRef.current.length}`)
        apply(j)
      } catch {
        stop()
      }
    }, POLL_MS)
  }, [apply, stop])

  const start = useCallback(async (body: Record<string, unknown>) => {
    stop()
    stepsRef.current = []
    setSteps([])
    const j = await api.post<AgentJob<T>>('/vision/agent/jobs', body)
    apply(j)
    if (j.status === 'running') schedule(j.id)
    return j
  }, [apply, schedule, stop])

  const cancel = useCallback(async () => {
    if (!job) return
    try {
      await api.post(`/vision/agent/jobs/${job.id}/cancel`)
    } catch {
      /* 已結束的工作取消失敗可忽略 */
    }
  }, [job])

  const answer = useCallback(async (answers: { id: string; answer: string }[]) => {
    if (!job) return
    const j = await api.post<AgentJob<T>>(`/vision/agent/jobs/${job.id}/answer`, { answers })
    apply(j)
    if (j.status === 'running') schedule(j.id)
  }, [apply, job, schedule])

  const reset = useCallback(() => {
    stop()
    stepsRef.current = []
    setSteps([])
    setJob(null)
  }, [stop])

  useEffect(() => stop, [stop])

  return {
    job,
    steps,
    running: job?.status === 'running',
    waiting: job?.status === 'needs_input',
    start,
    cancel,
    answer,
    reset,
  }
}
