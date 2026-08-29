/**
 * 依 Param.kind 產生一個表單欄位。kind 是封閉集合，所以這裡的 switch 要涵蓋全部；
 * roi / asset 兩種要跟影像檢視器互動，透過 InspectorActions 由編輯器頁面提供。
 */
import { useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Crop, Scan, Upload, X } from 'lucide-react'

import { Button, Checkbox, Select, TextArea, TextInput } from '@/components/ui'
import { useAssetMutations, useAssets, useConnections, useSources } from '@/lib/queries'
import type { Region, ToolParam } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'
import { errorMessage } from '@/lib/errors'

export interface InspectorActions {
  /** 正在於影像上編輯的 ROI 參數 key（null = 沒有） */
  roiEditingKey: string | null
  /** 開始／結束在影像上編輯某個 roi 參數 */
  setRoiEditing: (paramKey: string | null) => void
  /** 從目前影像框選建立範本；完成後回傳 asset id（取消回 null） */
  templateFromImage: (paramKey: string) => void
  /** 正在框選範本的參數 key */
  templateKey: string | null
  hasImage: boolean
}

function describeRegion(region: Region): string {
  switch (region.shape) {
    case 'rect':
      return `rect x=${region.x} y=${region.y} w=${region.w} h=${region.h}`
    case 'rotated_rect':
      return `rotated_rect c=(${region.cx}, ${region.cy}) ${region.w}×${region.h} ∠${region.angle}°`
    case 'circle':
      return `circle c=(${region.cx}, ${region.cy}) r=${region.r}`
    case 'annulus':
      return `annulus c=(${region.cx}, ${region.cy}) r=${region.r_inner}–${region.r_outer}`
    case 'polygon':
      return `polygon ${region.points.length} 點`
    case 'line':
      return `line (${region.x1}, ${region.y1}) → (${region.x2}, ${region.y2})`
    default:
      return JSON.stringify(region)
  }
}

function JsonField({ label, hint, value, onChange, mono = false, rows = 3 }: { label: string; hint?: string; value: unknown; onChange: (v: unknown) => void; mono?: boolean; rows?: number }) {
  const { t } = useTranslation()
  // 本地字串狀態：輸入到一半不是合法 JSON 時不要回寫（會把游標弄亂），只顯示錯誤。
  const [text, setText] = useState(() => (typeof value === 'string' ? value : value === undefined || value === null ? '' : JSON.stringify(value, null, 2)))
  const [error, setError] = useState<string | undefined>()
  return (
    <TextArea
      label={label}
      hint={hint}
      error={error}
      rows={rows}
      className={mono ? 'font-mono text-xs' : ''}
      value={text}
      onChange={(e) => {
        const next = e.target.value
        setText(next)
        if (!next.trim()) {
          setError(undefined)
          onChange(null)
          return
        }
        try {
          onChange(JSON.parse(next))
          setError(undefined)
        } catch {
          setError(t('editor.params.jsonInvalid'))
        }
      }}
    />
  )
}

export function ParamField({ param, value, onChange, actions }: { param: ToolParam; value: unknown; onChange: (value: unknown) => void; actions: InspectorActions }) {
  const { t } = useTranslation()
  const toast = useToast()
  const sources = useSources()
  const assets = useAssets(param.kind === 'asset' ? param.accept : '')
  const { uploadFile } = useAssetMutations()
  const fileInput = useRef<HTMLInputElement>(null)
  // write_plc 的 connection（kind=text）改用連線清單當 datalist，保留自由輸入。
  const isConnection = param.key === 'connection' && param.kind === 'text'
  const connections = useConnections(isConnection)
  const listId = useId()
  const text = value === null || value === undefined ? '' : String(value)
  const label = param.label
  const help = param.help_text || undefined

  switch (param.kind) {
    case 'boolean':
      return <Checkbox label={label} hint={help} checked={Boolean(value)} onChange={onChange} />

    case 'number':
      return (
        <TextInput
          label={label}
          type="number"
          required={param.required}
          suffix={param.unit || undefined}
          min={param.minimum ?? undefined}
          max={param.maximum ?? undefined}
          step={param.step ?? 'any'}
          hint={help}
          value={text}
          onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        />
      )

    case 'select':
      return (
        <Select label={label} required={param.required} hint={help} value={text} placeholder={param.required ? undefined : t('common.none')} onChange={(e) => onChange(e.target.value)} options={param.options.map((o) => ({ value: String(o.value), label: o.label }))} />
      )

    case 'range': {
      // 單一數值：滑桿 + 數字框（min/max/step 來自參數宣告）。
      const min = param.minimum ?? 0
      const max = param.maximum ?? 1
      const step = param.step ?? (max - min > 10 ? 1 : 0.01)
      const numeric = typeof value === 'number' ? value : Number(text)
      const current = Number.isFinite(numeric) ? numeric : min
      return (
        <div>
          <span className="label">
            {label}
            {param.required ? <span className="text-critical"> *</span> : null}
          </span>
          <div className="flex items-center gap-2">
            <input type="range" min={min} max={max} step={step} value={current} onChange={(e) => onChange(Number(e.target.value))} className="h-1 min-w-0 flex-1 cursor-pointer accent-[var(--brand)]" />
            <input type="number" min={min} max={max} step={step} value={text} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} className="input !w-24 tnum" />
            {param.unit ? <span className="text-xs text-subtle">{param.unit}</span> : null}
          </div>
          {help ? <p className="hint">{help}</p> : null}
        </div>
      )
    }

    case 'color':
      return (
        <div>
          <span className="label">{label}</span>
          <div className="flex items-center gap-2">
            <input type="color" value={/^#[0-9a-fA-F]{6}$/.test(text) ? text : '#00ff00'} onChange={(e) => onChange(e.target.value)} className="size-8 cursor-pointer rounded border border-line bg-transparent p-0" />
            <input className="input font-mono text-xs" value={text} onChange={(e) => onChange(e.target.value)} placeholder="#rrggbb" />
          </div>
          {help ? <p className="hint">{help}</p> : null}
        </div>
      )

    case 'json':
      return <JsonField label={label} hint={help} value={value} onChange={onChange} mono />

    case 'expression':
    case 'multiline':
      return <TextArea label={label} hint={help} rows={param.kind === 'expression' ? 2 : 4} className={param.kind === 'expression' ? 'font-mono text-xs' : ''} value={text} onChange={(e) => onChange(e.target.value)} />

    case 'source':
      return (
        <Select label={label} required={param.required} hint={help} value={text} placeholder={t('editor.params.pickSource')} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} options={(sources.data?.items ?? []).map((s) => ({ value: String(s.id), label: `${s.name}（${s.kind}）`, disabled: !s.is_enabled }))} />
      )

    case 'asset': {
      const accept = param.accept || 'image'
      const isImage = accept === 'image'
      const selecting = actions.templateKey === param.key
      return (
        <div>
          <Select label={label} required={param.required} hint={help} value={text} placeholder={t('editor.params.pickAsset')} onChange={(e) => onChange(e.target.value || null)} options={(assets.data?.items ?? []).map((a) => ({ value: a.id, label: a.name }))} />
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Button size="xs" icon={<Upload size={12} />} loading={uploadFile.isPending} onClick={() => fileInput.current?.click()}>
              {t('editor.params.uploadAsset')}
            </Button>
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              accept={isImage ? 'image/*' : undefined}
              onChange={async (e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (!file) return
                try {
                  const asset = await uploadFile.mutateAsync({ file, kind: accept as 'image' | 'model' | 'file' })
                  onChange(asset.id)
                  toast.success(t('editor.toast.assetUploaded', { name: asset.name }))
                } catch (error) {
                  toast.error(errorMessage(error))
                }
              }}
            />
            {isImage ? (
              <Button size="xs" icon={selecting ? <X size={12} /> : <Scan size={12} />} active={selecting} disabled={!actions.hasImage && !selecting} title={actions.hasImage ? undefined : t('editor.viewer.noImageForTemplate')} onClick={() => actions.templateFromImage(selecting ? '' : param.key)}>
                {selecting ? t('common.cancel') : t('editor.viewer.templateFromImage')}
              </Button>
            ) : null}
          </div>
          {selecting ? <p className="hint text-brand">{t('editor.viewer.templateHint')}</p> : null}
        </div>
      )
    }

    case 'roi': {
      const region = value && typeof value === 'object' && 'shape' in (value as object) ? (value as Region) : null
      const editing = actions.roiEditingKey === param.key
      return (
        <div>
          <span className="label">
            {label}
            {param.required ? <span className="text-critical"> *</span> : null}
          </span>
          <div className="rounded-lg border border-line bg-surface-muted/50 px-2.5 py-1.5 font-mono text-[11px] text-muted">
            {region ? describeRegion(region) : t('editor.params.roiNone')}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Button size="xs" icon={<Crop size={12} />} active={editing} disabled={!actions.hasImage && !editing} title={actions.hasImage ? undefined : t('editor.viewer.noImageForTemplate')} onClick={() => actions.setRoiEditing(editing ? null : param.key)}>
              {editing ? t('editor.viewer.done') : t('editor.viewer.editRoi')}
            </Button>
            {region ? (
              <Button size="xs" variant="ghost" icon={<X size={12} />} onClick={() => { onChange(null); if (editing) actions.setRoiEditing(null) }}>
                {t('editor.viewer.clearRoi')}
              </Button>
            ) : null}
          </div>
          {editing ? <p className="hint text-brand">{t('editor.viewer.roiEditing')}</p> : null}
          {param.shapes.length ? <p className="hint">{t('editor.params.roiShape')}：{param.shapes.join(', ')}</p> : null}
          {help ? <p className="hint">{help}</p> : null}
        </div>
      )
    }

    case 'output_key':
    case 'text':
    default:
      if (isConnection) {
        const items = connections.data?.items ?? []
        return (
          <div>
            <TextInput label={label} required={param.required} hint={items.length ? help || t('editor.params.connectionHint') : t('editor.params.connectionNone')} value={text} list={listId} onChange={(e) => onChange(e.target.value)} data-testid="param-connection" />
            <datalist id={listId}>{items.map((c) => <option key={c.id} value={c.name}>{`${c.kind}${c.is_enabled ? '' : ' (disabled)'}`}</option>)}</datalist>
          </div>
        )
      }
      return <TextInput label={label} required={param.required} hint={help} className={param.kind === 'output_key' ? 'font-mono' : ''} value={text} onChange={(e) => onChange(e.target.value)} />
  }
}
