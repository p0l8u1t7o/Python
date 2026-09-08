/**
 * 相機間映射精靈：在兩張影像收集對應點，解出 A 像素到 B 像素的映射。
 */
import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, Trash2, Upload } from 'lucide-react'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import {
  Badge, Button, Card, CardBody, CardHeader, EmptyRow, EmptyState, IconButton,
  Select, TBody, THead, Table, Td, Th, Tr,
} from '@/components/ui'
import { api, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useSources } from '@/lib/queries'
import type { Overlay } from '@/lib/types'

type Side = 'a' | 'b'
export type MappingKind = 'affine' | 'perspective'

interface MappingShot {
  ref: string
  width: number
  height: number
  name: string
}

interface MappingPair {
  a: [number, number] | null
  b: [number, number] | null
  error: number | null
}

export interface MappingBlock {
  kind: MappingKind
  matrix: number[][]
  rms: number
  max_error: number
  points: { ax: number; ay: number; bx: number; by: number; error: number }[]
}

const MAX_POINTS = 200

export function useMappingWizard() {
  const [kind, setKind] = useState<MappingKind>('affine')
  const [sourceA, setSourceA] = useState('')
  const [sourceB, setSourceB] = useState('')
  const [shotA, setShotA] = useState<MappingShot | null>(null)
  const [shotB, setShotB] = useState<MappingShot | null>(null)
  const [active, setActive] = useState<Side>('a')
  const [pairs, setPairs] = useState<MappingPair[]>([])
  const [busySide, setBusySide] = useState<Side | ''>('')

  function reset() {
    setShotA(null)
    setShotB(null)
    setActive('a')
    setPairs([])
  }

  function clearPoints() {
    setPairs([])
    setActive('a')
  }

  function setShot(side: Side, shot: MappingShot) {
    if (side === 'a') setShotA(shot)
    else setShotB(shot)
    clearPoints()
  }

  async function capture(side: Side) {
    const source = side === 'a' ? sourceA : sourceB
    if (!source) return ''
    setBusySide(side)
    try {
      const shot = await api.post<MappingShot>('/vision/calibration/capture', {}, { source_id: Number(source) })
      setShot(side, shot)
      return ''
    } catch (err) {
      return errorMessage(err)
    } finally {
      setBusySide('')
    }
  }

  async function upload(side: Side, files: FileList | null) {
    if (!files?.length) return ''
    setBusySide(side)
    try {
      const form = new FormData()
      form.append('image', files[0])
      const shot = await api.postForm<MappingShot>('/vision/calibration/capture', form)
      setShot(side, { ...shot, name: files[0].name })
      return ''
    } catch (err) {
      return errorMessage(err)
    } finally {
      setBusySide('')
    }
  }

  function record(side: Side, point: [number, number]) {
    setPairs((prev) => {
      const next = prev.map((p) => ({ ...p, error: null }))
      if (side === 'a') {
        const open = next.findIndex((p) => p.a == null)
        if (open >= 0) next[open] = { ...next[open], a: point }
        else if (next.length < MAX_POINTS) next.push({ a: point, b: null, error: null })
        setActive('b')
      } else {
        const open = next.findIndex((p) => p.a != null && p.b == null)
        if (open >= 0) next[open] = { ...next[open], b: point }
        else if (next.length < MAX_POINTS) next.push({ a: null, b: point, error: null })
        setActive('a')
      }
      return next
    })
  }

  const complete = pairs.filter((p) => p.a && p.b) as { a: [number, number]; b: [number, number]; error: number | null }[]
  const canSolve = !!shotA && !!shotB && complete.length >= (kind === 'perspective' ? 4 : 3)

  function body() {
    return {
      mode: 'mapping',
      image_size: [shotA?.width ?? shotB?.width ?? 1, shotA?.height ?? shotB?.height ?? 1],
      kind,
      from_source: shotA?.name ?? '',
      to_source: shotB?.name ?? '',
      points: complete.map((p) => ({ a: p.a, b: p.b })),
    }
  }

  function applyResult(mapping: MappingBlock | null) {
    setPairs((prev) => prev.map((p, i) => ({ ...p, error: mapping?.points?.[i]?.error ?? null })))
  }

  function overlays(side: Side): Overlay[] {
    const worst = pairs.reduce((m, p) => Math.max(m, p.error ?? 0), 0)
    return pairs.flatMap((p, i) => {
      const point = side === 'a' ? p.a : p.b
      if (!point) return []
      const bad = p.error != null && worst > 0 && p.error >= worst
      return [{ kind: 'point', x: point[0], y: point[1], color: bad ? '#ef4444' : '#22c55e', label: p.error != null ? `${i + 1}: ${p.error.toFixed(3)}` : String(i + 1) } as Overlay]
    })
  }

  return {
    kind, setKind, sourceA, setSourceA, sourceB, setSourceB, shotA, shotB, active, setActive,
    pairs, setPairs, busySide, capture, upload, record, reset, clearPoints, canSolve, body, applyResult, overlays,
  }
}

type Wizard = ReturnType<typeof useMappingWizard>

interface Props {
  wizard: Wizard
  onChange: () => void
  onError: (message: string) => void
}

export function MappingWizard({ wizard, onChange, onError }: Props) {
  const { t } = useTranslation()
  const sources = useSources()
  const fileA = useRef<HTMLInputElement>(null)
  const fileB = useRef<HTMLInputElement>(null)
  const sourceOptions = (sources.data?.items ?? []).map((s) => ({ value: String(s.id), label: s.name }))
  const complete = wizard.pairs.filter((p) => p.a && p.b).length
  const need = wizard.kind === 'perspective' ? 4 : 3
  const worst = useMemo(() => Math.max(0, ...wizard.pairs.map((p) => p.error ?? 0)), [wizard.pairs])

  function choose(side: Side, point: [number, number]) {
    wizard.record(side, point)
    onChange()
  }

  function remove(index: number) {
    wizard.setPairs((prev) => prev.filter((_, i) => i !== index))
    onChange()
  }

  async function grab(side: Side) {
    const err = await wizard.capture(side)
    if (err) onError(err)
    else onChange()
  }

  async function put(side: Side, files: FileList | null) {
    const err = await wizard.upload(side, files)
    if (err) onError(err)
    else onChange()
  }

  function imageCard(side: Side) {
    const shot = side === 'a' ? wizard.shotA : wizard.shotB
    const source = side === 'a' ? wizard.sourceA : wizard.sourceB
    const file = side === 'a' ? fileA : fileB
    return (
      <Card>
        <CardHeader
          title={t(`calibration.mapping.camera.${side}`)}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={source}
                onChange={(e) => side === 'a' ? wizard.setSourceA(e.target.value) : wizard.setSourceB(e.target.value)}
                placeholder={t('calibration.pickSource')}
                options={sourceOptions}
                data-testid={`calib-mapping-source-${side}`}
              />
              <Button icon={<Camera size={14} />} disabled={!source} loading={wizard.busySide === side} onClick={() => void grab(side)} data-testid={`calib-mapping-capture-${side}`}>
                {t('calibration.capture')}
              </Button>
              <Button icon={<Upload size={14} />} loading={wizard.busySide === side} onClick={() => file.current?.click()} data-testid={`calib-mapping-upload-${side}`}>
                {t('calibration.upload')}
              </Button>
              <input ref={file} type="file" accept="image/*" className="hidden" onChange={(e) => { void put(side, e.target.files); e.target.value = '' }} />
            </div>
          }
        />
        <CardBody>
          {shot ? (
            <ImageViewer
              src={imageUrl(shot.ref, 1200)}
              imageWidth={shot.width}
              imageHeight={shot.height}
              overlays={wizard.overlays(side)}
              onPick={(x, y) => choose(side, [x, y])}
              className={`h-[320px] ${wizard.active === side ? 'ring-2 ring-brand' : ''}`}
              stateKey={`calibration:mapping:${side}`}
            />
          ) : (
            <EmptyState title={t('calibration.noPicture')} description={t('calibration.noPictureHint')} icon={<Camera size={22} />} />
          )}
        </CardBody>
      </Card>
    )
  }

  return (
    <div className="space-y-4" data-testid="calib-mapping-wizard">
      <div className="grid gap-4 xl:grid-cols-2">
        {imageCard('a')}
        {imageCard('b')}
      </div>
      <Card>
        <CardHeader
          title={t('calibration.mapping.title')}
          actions={<Badge tone={wizard.active === 'a' ? 'neutral' : 'ok'}>{t(`calibration.mapping.next.${wizard.active}`)}</Badge>}
        />
        <CardBody className="space-y-3">
          <Select
            label={t('calibration.mapping.kind')}
            value={wizard.kind}
            onChange={(e) => { wizard.setKind(e.target.value as MappingKind); onChange() }}
            options={(['affine', 'perspective'] as MappingKind[]).map((k) => ({ value: k, label: t(`calibration.mapping.kinds.${k}`) }))}
            hint={t(`calibration.mapping.kindHints.${wizard.kind}`)}
            data-testid="calib-mapping-kind"
          />
          <p className="text-xs text-subtle">{t('calibration.mapping.count', { count: complete, need })}</p>
          <Table>
            <THead>
              <Th>#</Th>
              <Th>{t('calibration.mapping.camera.a')}</Th>
              <Th>{t('calibration.mapping.camera.b')}</Th>
              <Th align="right">{t('calibration.pointError')}</Th>
              <Th />
            </THead>
            <TBody>
              {wizard.pairs.length ? wizard.pairs.map((p, i) => {
                const worstRow = p.error != null && worst > 0 && p.error >= worst
                return (
                  <Tr key={i} testId={`calib-mapping-point-${i}`} className={worstRow ? 'bg-critical/10' : undefined}>
                    <Td>{i + 1}</Td>
                    <Td>{p.a ? `${p.a[0].toFixed(1)}, ${p.a[1].toFixed(1)}` : '-'}</Td>
                    <Td>{p.b ? `${p.b[0].toFixed(1)}, ${p.b[1].toFixed(1)}` : '-'}</Td>
                    <Td align="right">{p.error == null ? '-' : `${p.error.toFixed(3)} px`}</Td>
                    <Td align="right">
                      <IconButton label={t('common.delete')} onClick={() => remove(i)}>
                        <Trash2 size={13} />
                      </IconButton>
                    </Td>
                  </Tr>
                )
              }) : <EmptyRow colSpan={5} message={t('calibration.noPoints')} />}
            </TBody>
          </Table>
        </CardBody>
      </Card>
    </div>
  )
}

export function MappingResult({ mapping }: { mapping: MappingBlock }) {
  const { t } = useTranslation()
  const matrix = mapping.matrix
  const precision = Math.sqrt(Math.abs(matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]))
  return (
    <div className="space-y-1 text-sm" data-testid="calib-mapping-result">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-xl font-semibold tabular-nums">{mapping.rms.toFixed(4)}</span>
        <span className="text-xs text-subtle">{t('calibration.mapping.rms')}</span>
      </div>
      <p className="text-xs text-subtle">{t('calibration.fitError', { rms: mapping.rms.toFixed(3), max: mapping.max_error.toFixed(3), unit: 'px' })}</p>
      <p className="text-xs text-subtle" data-testid="calib-mapping-precision">
        {t('calibration.mapping.precision', { value: Number(precision.toPrecision(6)).toString() })}
      </p>
    </div>
  )
}
