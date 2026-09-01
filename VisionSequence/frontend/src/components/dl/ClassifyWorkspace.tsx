/**
 * ClassifyWorkspace — classes 模式（整張影像一個類別）的大圖檢視工作區。
 * 左：縮圖牆（顯示已標類別色條）；右：ImageViewer 看原圖（可縮放／1:1／平移）＋類別按鈕標記。
 * 網格模式適合大量快速標記，這裡則是「看清楚細節再決定」用的；兩者共用同一份樣本與類別。
 * 快捷鍵：←/→（或 A/D）換張、0~9 指定類別（刪除樣本只給按鈕，避免誤按 Delete 刪掉整張）。
 */
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, Sparkles, Trash2 } from 'lucide-react'

import { ImageViewer } from '@/components/viewer/ImageViewer'
import { Button, IconButton } from '@/components/ui'
import { dlSampleUrl } from '@/lib/api'
import { classColor } from '@/lib/colors'
import type { DlProject, DlSample, DlSuggestion } from '@/lib/types'
import { Thumb } from './Thumb'
import { nextSplit } from './split'

function isTyping(): boolean {
  const el = document.activeElement
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || (el as HTMLElement).isContentEditable)
}

export function ClassifyWorkspace({ project, samples, suggestions, selectedId, onSelect, onLabel, onSetSplit, onDelete, hotkeysDisabled = false }: {
  project: DlProject
  samples: DlSample[]
  suggestions: Map<string, DlSuggestion>
  selectedId: string | null
  onSelect: (id: string) => void
  onLabel: (sample: DlSample, label: string) => void
  /** 點分割 chip 循環切換 train/val/test/未指定 */
  onSetSplit?: (sample: DlSample, split: DlSample['split']) => void
  onDelete: (sample: DlSample) => void
  hotkeysDisabled?: boolean
}) {
  const { t } = useTranslation()
  const classes = project.classes
  const sample = samples.find((s) => s.id === selectedId) ?? samples[0] ?? null
  const index = sample ? samples.findIndex((s) => s.id === sample.id) : -1

  function step(delta: number) {
    const next = samples[index + delta]
    if (next) onSelect(next.id)
  }

  // ←/→、0~9、Delete：掛 capture 讓數字鍵先於檢視器的 1:1 縮放（同 ShapeWorkspace 的做法）
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (hotkeysDisabled || isTyping() || e.ctrlKey || e.metaKey || e.altKey || !sample) return
      const key = e.key.toLowerCase()
      if (/^[0-9]$/.test(key)) {
        const label = classes[Number(key)]
        if (!label) return
        onLabel(sample, sample.label === label ? '' : label)
      } else if (key === 'arrowleft' || key === 'a') step(-1)
      else if (key === 'arrowright' || key === 'd') step(1)
      else return
      e.preventDefault()
      e.stopPropagation()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  })

  if (!sample) return null
  const suggestion = suggestions.get(sample.id)
  return (
    <div className="grid gap-3 lg:h-[calc(100vh-320px)] lg:min-h-[460px] lg:grid-cols-[180px_minmax(0,1fr)]">
      <div className="max-h-[50vh] space-y-1.5 overflow-y-auto pr-1 lg:h-full lg:max-h-none" data-testid="dl-classify-thumbs">
        {samples.map((s) => (
          <Thumb key={s.id} sample={s} classes={classes} selected={s.id === sample.id} labelText={s.label} onClick={() => onSelect(s.id)} />
        ))}
      </div>

      <div className="flex min-h-0 min-w-0 flex-col gap-2">
        {/* 狀態列 */}
        <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-2 gap-y-1">
          <IconButton label={t('dl.prevSample')} size="md" variant="secondary" onClick={() => step(-1)}><ChevronLeft size={16} /></IconButton>
          <IconButton label={t('dl.nextSample')} size="md" variant="secondary" onClick={() => step(1)}><ChevronRight size={16} /></IconButton>
          <span className="tnum text-xs text-muted">{index + 1} / {samples.length}</span>
          <span className="text-xs text-subtle">{sample.width}×{sample.height}</span>
          {onSetSplit ? (
            <button type="button" title={t('dl.splitCycleHint')} onClick={() => onSetSplit(sample, nextSplit(sample.split))}
              className={`rounded border px-1.5 py-0.5 text-[11px] transition-colors hover:bg-surface-muted ${sample.split ? 'border-line font-medium text-content' : 'border-dashed border-line text-subtle'}`}
              data-testid="dl-split-chip">
              {t(`dl.split.${sample.split || 'unassigned'}`)}
            </button>
          ) : null}
          {sample.label ? (
            <span className="rounded px-2 py-0.5 text-xs font-medium text-white" style={{ background: classColor(classes, sample.label) }}>
              {sample.label}{sample.labeled_by === 'auto' ? ` · ${t('dl.filterAuto')}` : ''}
            </span>
          ) : suggestion ? (
            <span className="flex items-center gap-1 text-xs text-warning"><Sparkles size={12} />{suggestion.label}? {Math.round(suggestion.score * 100)}%</span>
          ) : (
            <span className="text-xs text-muted">{t('dl.unlabeled')}</span>
          )}
          <span className="ml-auto" />
          <Button size="md" variant="ghost" onClick={() => onDelete(sample)} title={t('common.delete')}><Trash2 size={15} /></Button>
        </div>

        {/* 類別按鈕：點一下就把目前這張標成該類（再點一次取消） */}
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {classes.map((c, i) => {
            const active = sample.label === c
            return (
              <button key={c} type="button" onClick={() => onLabel(sample, active ? '' : c)} title={t('dl.classButtonTitle', { n: i })}
                className={`flex h-11 items-center gap-2 rounded-md border px-3 text-sm font-medium transition-colors ${active ? 'border-transparent text-white shadow-sm' : 'border-line text-content hover:bg-surface-muted'}`}
                style={active ? { background: classColor(classes, c) } : undefined} data-testid={`dl-view-class-${c}`}>
                <span className="size-3 shrink-0 rounded-full border border-black/10" style={{ background: active ? '#fff' : classColor(classes, c) }} />
                <span className="min-w-0 max-w-32 truncate">{c}</span>
                {i <= 9 ? <kbd className={`rounded border px-1 text-[10px] leading-4 ${active ? 'border-white/40 text-white/85' : 'border-line text-subtle'}`}>{i}</kbd> : null}
              </button>
            )
          })}
          {!classes.length ? <span className="text-xs text-warning">{t('dl.classesFirst')}</span> : null}
        </div>

        <div className="h-[55vh] min-h-[380px] lg:h-auto lg:min-h-0 lg:flex-1">
          <ImageViewer
            className="h-full w-full"
            src={dlSampleUrl(sample.id, 1600)}
            imageWidth={sample.width}
            imageHeight={sample.height}
            badge={sample.label ? { text: sample.label, tone: 'neutral' } : null}
          />
        </div>
      </div>
    </div>
  )
}
