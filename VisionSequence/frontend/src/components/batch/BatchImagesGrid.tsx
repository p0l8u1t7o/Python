/** 影像集分頁：縮圖網格＋每張的期望標記（—／OK／NG）與備註；有選定執行時疊上判定與命中記號。 */
import { useTranslation } from 'react-i18next'

import { Button, SegmentedControl } from '@/components/ui'
import { batchImageUrl, type BatchRun, type BatchSet, type Expected } from '@/lib/batch'

export function BatchImagesGrid({ set, run, onLabel, onBulk, onPreview, canManage }: {
  set: BatchSet
  run: BatchRun | null
  onLabel: (index: number, expected: Expected) => void
  onBulk: (expected: Expected) => void
  onPreview: (index: number) => void
  canManage: boolean
}) {
  const { t } = useTranslation()
  const byIndex = new Map((run?.items ?? []).map((it) => [it.index, it]))
  const images = set.images ?? []
  return (
    <div className="space-y-2" data-testid="batch-images">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>{t('batchPage.labelHint')}</span>
        <span className="ml-auto flex gap-1">
          <Button size="xs" disabled={!canManage} onClick={() => onBulk('ok')}>{t('batchPage.labelAllOk')}</Button>
          <Button size="xs" disabled={!canManage} onClick={() => onBulk('ng')}>{t('batchPage.labelAllNg')}</Button>
          <Button size="xs" disabled={!canManage} onClick={() => onBulk('')}>{t('batchPage.labelClear')}</Button>
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {images.map((im) => {
          const it = byIndex.get(im.index)
          const st = it?.status
          return (
            <div key={im.index} className={`rounded-lg border p-1.5 ${it?.match === false ? 'border-critical/50' : 'border-line'}`} data-testid="batch-image-card">
              <button type="button" className="relative block w-full" onClick={() => onPreview(im.index)} title={t('batchPage.previewHint')}>
                <img src={batchImageUrl(set.id, im.index, 256)} alt={im.name} className="h-28 w-full rounded bg-surface-muted object-contain" loading="lazy" />
                <span className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[9px] text-white">#{im.index + 1}</span>
                {st ? <span className={`absolute bottom-1 left-1 rounded px-1 text-[9px] font-semibold text-white ${st === 'ok' ? 'bg-ok' : st === 'ng' ? 'bg-critical' : 'bg-neutral-500'}`}>{st.toUpperCase()}{it?.match === false ? ' ✗' : it?.match ? ' ✓' : ''}</span> : null}
              </button>
              <p className="mt-1 truncate text-[11px]" title={im.name}>{im.name}</p>
              <div className="mt-1 flex items-center justify-between gap-1">
                <SegmentedControl size="sm" value={im.expected} onChange={(v) => { if (canManage) onLabel(im.index, v) }} options={[
                  { value: '', label: t('batchPage.expectNone') }, { value: 'ok', label: 'OK' }, { value: 'ng', label: 'NG' },
                ]} />
                <span className="tnum text-[10px] text-subtle">{im.width}×{im.height}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
