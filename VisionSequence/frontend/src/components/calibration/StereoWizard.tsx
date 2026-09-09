/**
 * 雙視野標定精靈：維持左右成對影像、殘差表與高度基準輸入。
 */
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, Trash2, Upload } from 'lucide-react'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import {
  Badge, Button, Card, CardBody, CardHeader, EmptyRow, EmptyState, IconButton,
  Select, TBody, THead, Table, Td, TextInput, Th, Tr,
} from '@/components/ui'
import { api, imageUrl, importStereoCalibration, saveStereoReference } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useAssets, useSources } from '@/lib/queries'
import type { CalibrationSolveResult, Overlay, Region } from '@/lib/types'

type BoardKind = 'chessboard' | 'circles' | 'acircles'

interface StereoShot {
  ref: string
  width: number
  height: number
  name: string
  corners: number[][] | null
  overlays: Overlay[]
  hint: string
}

interface StereoPair {
  left: StereoShot
  right: StereoShot
  dt_ms: number | null
  error: number | null
}

export interface StereoBlock {
  rms: number
  baseline_mm: number
  points?: { index: number; error: number }[]
  image_size?: [number, number]
  z_ref?: { d0_mm: number; Z0_mm: number; scale: number }
}

export function useStereoWizard() {
  const [leftSource, setLeftSource] = useState('')
  const [rightSource, setRightSource] = useState('')
  const [boardKind, setBoardKind] = useState<BoardKind>('chessboard')
  const [cols, setCols] = useState('9')
  const [rows, setRows] = useState('6')
  const [spacing, setSpacing] = useState('20')
  const [pairs, setPairs] = useState<StereoPair[]>([])
  const [active, setActive] = useState<'left' | 'right'>('left')
  const [busy, setBusy] = useState(false)
  const [zAsset, setZAsset] = useState('')
  const [z0, setZ0] = useState('0')
  const [zScale, setZScale] = useState('1')
  const [roi, setRoi] = useState<Region>({ shape: 'rect', x: 0, y: 0, w: 200, h: 120 })

  function reset() {
    setPairs([])
    setActive('left')
  }

  function applyResult(stereo: StereoBlock | null) {
    setPairs((prev) => prev.map((p, i) => ({ ...p, error: stereo?.points?.[i]?.error ?? null })))
  }

  const goodPairs = pairs.filter((p) => p.left.corners?.length && p.right.corners?.length)
  const canSolve = goodPairs.length >= 5 && Number(cols) > 0 && Number(rows) > 0 && Number(spacing) > 0

  function body() {
    return {
      mode: 'stereo',
      kind: boardKind,
      board_kind: boardKind,
      cols: Number(cols),
      rows: Number(rows),
      spacing: Number(spacing),
      image_size: [pairs[0]?.left.width ?? 1, pairs[0]?.left.height ?? 1],
      left_source: leftSource,
      right_source: rightSource,
      views_left: goodPairs.map((p) => p.left.corners),
      views_right: goodPairs.map((p) => p.right.corners),
    }
  }

  const overlays = active === 'left'
    ? pairs.at(-1)?.left.overlays ?? []
    : pairs.at(-1)?.right.overlays ?? []

  return {
    leftSource, setLeftSource, rightSource, setRightSource, boardKind, setBoardKind,
    cols, setCols, rows, setRows, spacing, setSpacing, pairs, setPairs, active, setActive,
    busy, setBusy, zAsset, setZAsset, z0, setZ0, zScale, setZScale, roi, setRoi,
    reset, applyResult, body, canSolve, overlays,
  }
}

type Wizard = ReturnType<typeof useStereoWizard>

interface Props {
  wizard: Wizard
  onChange: () => void
  onError: (message: string) => void
  onSolved: (result: CalibrationSolveResult) => void
}

async function detectShot(shot: Omit<StereoShot, 'corners' | 'overlays' | 'hint'>, boardKind: BoardKind, cols: string, rows: string): Promise<StereoShot> {
  try {
    const body = await api.post<{ found: boolean; corners: number[][]; overlays: Overlay[]; hint?: string }>(
      '/vision/calibration/detect',
      { ref: shot.ref, kind: boardKind, cols: Number(cols), rows: Number(rows) },
    )
    return { ...shot, corners: body.found ? body.corners : null, overlays: body.overlays ?? [], hint: body.hint ?? '' }
  } catch (err) {
    return { ...shot, corners: null, overlays: [], hint: errorMessage(err) }
  }
}

export function StereoWizard({ wizard, onChange, onError, onSolved }: Props) {
  const { t } = useTranslation()
  const sources = useSources()
  const assets = useAssets('calibration')
  const importRef = useRef<HTMLInputElement>(null)
  const leftUpload = useRef<HTMLInputElement>(null)
  const rightUpload = useRef<HTMLInputElement>(null)
  const sourceOptions = (sources.data?.items ?? []).map((s) => ({ value: String(s.id), label: s.name }))
  const assetOptions = (assets.data?.items ?? []).map((a) => ({ value: a.id, label: a.name }))
  const last = wizard.pairs.at(-1)
  const shown = wizard.active === 'left' ? last?.left : last?.right

  async function captureOne(source: string) {
    return api.post<{ ref: string; width: number; height: number; name: string }>('/vision/calibration/capture', {}, { source_id: Number(source) })
  }

  async function capturePair() {
    if (!wizard.leftSource || !wizard.rightSource) return
    wizard.setBusy(true)
    try {
      const t0 = performance.now()
      const left = await captureOne(wizard.leftSource)
      const right = await captureOne(wizard.rightSource)
      const dt_ms = performance.now() - t0
      const pair = {
        left: await detectShot(left, wizard.boardKind, wizard.cols, wizard.rows),
        right: await detectShot(right, wizard.boardKind, wizard.cols, wizard.rows),
        dt_ms,
        error: null,
      }
      wizard.setPairs((prev) => [...prev, pair])
      onChange()
    } catch (err) {
      onError(errorMessage(err))
    } finally {
      wizard.setBusy(false)
    }
  }

  async function uploadSide(side: 'left' | 'right', files: FileList | null) {
    if (!files?.length) return
    wizard.setBusy(true)
    try {
      const form = new FormData()
      form.append('image', files[0])
      const raw = await api.postForm<{ ref: string; width: number; height: number; name: string }>('/vision/calibration/capture', form)
      const shot = await detectShot({ ...raw, name: files[0].name }, wizard.boardKind, wizard.cols, wizard.rows)
      wizard.setPairs((prev) => {
        const next = [...prev]
        const open = next.findIndex((p) => side === 'left' ? !p.left.ref : !p.right.ref)
        const empty: StereoShot = { ref: '', width: 0, height: 0, name: '', corners: null, overlays: [], hint: '' }
        const index = open >= 0 ? open : next.length
        const current = next[index] ?? { left: empty, right: empty, dt_ms: null, error: null }
        next[index] = { ...current, [side]: shot, error: null }
        return next
      })
      onChange()
    } catch (err) {
      onError(errorMessage(err))
    } finally {
      wizard.setBusy(false)
    }
  }

  async function importConfig(files: FileList | null) {
    if (!files?.length) return
    wizard.setBusy(true)
    try {
      const result = await importStereoCalibration(files[0])
      onSolved(result)
    } catch (err) {
      onError(errorMessage(err))
    } finally {
      wizard.setBusy(false)
    }
  }

  async function measureReference() {
    const pair = last
    if (!pair?.left.ref || !pair.right.ref || !wizard.zAsset) return
    wizard.setBusy(true)
    try {
      const result = await saveStereoReference({
        asset_id: wizard.zAsset,
        left_ref: pair.left.ref,
        right_ref: pair.right.ref,
        roi: wizard.roi,
        Z0_mm: Number(wizard.z0),
        scale: Number(wizard.zScale) || 1,
      })
      onSolved(result)
    } catch (err) {
      onError(errorMessage(err))
    } finally {
      wizard.setBusy(false)
    }
  }

  function remove(index: number) {
    wizard.setPairs((prev) => prev.filter((_, i) => i !== index))
    onChange()
  }

  return (
    <div className="space-y-4" data-testid="calib-stereo-wizard">
      <Card>
        <CardHeader
          title={t('calibration.stereo.title')}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Select value={wizard.leftSource} onChange={(e) => wizard.setLeftSource(e.target.value)} placeholder={t('calibration.stereo.leftSource')} options={sourceOptions} />
              <Select value={wizard.rightSource} onChange={(e) => wizard.setRightSource(e.target.value)} placeholder={t('calibration.stereo.rightSource')} options={sourceOptions} />
              <Button icon={<Camera size={14} />} loading={wizard.busy} disabled={!wizard.leftSource || !wizard.rightSource} onClick={() => void capturePair()} data-testid="calib-stereo-capture">
                {t('calibration.stereo.capturePair')}
              </Button>
              <Button icon={<Upload size={14} />} loading={wizard.busy} onClick={() => importRef.current?.click()} data-testid="calib-stereo-import">
                {t('calibration.stereo.importConfig')}
              </Button>
              <input ref={importRef} type="file" accept="application/json,.json" className="hidden" onChange={(e) => { void importConfig(e.target.files); e.target.value = '' }} />
            </div>
          }
        />
        <CardBody className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            {shown?.ref ? (
              <ImageViewer src={imageUrl(shown.ref, 1200)} imageWidth={shown.width} imageHeight={shown.height} overlays={wizard.overlays} className="h-[360px]" stateKey={`calibration:stereo:${wizard.active}`} />
            ) : (
              <EmptyState title={t('calibration.noPicture')} description={t('calibration.noPictureHint')} icon={<Camera size={22} />} />
            )}
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <Button variant={wizard.active === 'left' ? 'primary' : 'secondary'} onClick={() => wizard.setActive('left')}>{t('calibration.stereo.left')}</Button>
                <Button variant={wizard.active === 'right' ? 'primary' : 'secondary'} onClick={() => wizard.setActive('right')}>{t('calibration.stereo.right')}</Button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Button icon={<Upload size={14} />} loading={wizard.busy} onClick={() => leftUpload.current?.click()}>{t('calibration.stereo.uploadLeft')}</Button>
                <Button icon={<Upload size={14} />} loading={wizard.busy} onClick={() => rightUpload.current?.click()}>{t('calibration.stereo.uploadRight')}</Button>
                <input ref={leftUpload} type="file" accept="image/*" className="hidden" onChange={(e) => { void uploadSide('left', e.target.files); e.target.value = '' }} />
                <input ref={rightUpload} type="file" accept="image/*" className="hidden" onChange={(e) => { void uploadSide('right', e.target.files); e.target.value = '' }} />
              </div>
              <Select label={t('calibration.boardKind')} value={wizard.boardKind} onChange={(e) => wizard.setBoardKind(e.target.value as BoardKind)} options={(['chessboard', 'circles', 'acircles'] as BoardKind[]).map((k) => ({ value: k, label: t(`calibration.boardKinds.${k}`) }))} />
              <div className="grid grid-cols-3 gap-2">
                <TextInput label={t('calibration.cols')} value={wizard.cols} inputMode="numeric" onChange={(e) => wizard.setCols(e.target.value)} />
                <TextInput label={t('calibration.rows')} value={wizard.rows} inputMode="numeric" onChange={(e) => wizard.setRows(e.target.value)} />
                <TextInput label={t('calibration.spacing')} value={wizard.spacing} inputMode="decimal" suffix="mm" onChange={(e) => wizard.setSpacing(e.target.value)} />
              </div>
            </div>
          </div>
          <Table>
            <THead>
              <Th>#</Th>
              <Th>{t('calibration.stereo.left')}</Th>
              <Th>{t('calibration.stereo.right')}</Th>
              <Th align="right">{t('calibration.stereo.dt')}</Th>
              <Th align="right">{t('calibration.pointError')}</Th>
              <Th />
            </THead>
            <TBody>
              {wizard.pairs.length ? wizard.pairs.map((p, i) => (
                <Tr key={`${p.left.ref}-${p.right.ref}-${i}`} testId={`calib-stereo-pair-${i}`}>
                  <Td>{i + 1}</Td>
                  <Td>{p.left.corners?.length ? <Badge tone="ok">{p.left.corners.length}</Badge> : <Badge tone="critical">{t('calibration.notFound')}</Badge>}</Td>
                  <Td>{p.right.corners?.length ? <Badge tone="ok">{p.right.corners.length}</Badge> : <Badge tone="critical">{t('calibration.notFound')}</Badge>}</Td>
                  <Td align="right">{p.dt_ms == null ? '-' : `${p.dt_ms.toFixed(1)} ms`}</Td>
                  <Td align="right">{p.error == null ? '-' : `${p.error.toFixed(3)} px`}</Td>
                  <Td align="right"><IconButton label={t('common.delete')} onClick={() => remove(i)}><Trash2 size={13} /></IconButton></Td>
                </Tr>
              )) : <EmptyRow colSpan={6} message={t('calibration.noShots')} />}
            </TBody>
          </Table>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t('calibration.stereo.reference')} />
        <CardBody className="space-y-3">
          <Select label={t('calibration.stereo.savedAsset')} value={wizard.zAsset} onChange={(e) => wizard.setZAsset(e.target.value)} options={assetOptions} />
          <div className="grid grid-cols-2 gap-2">
            <TextInput label="Z0" value={wizard.z0} inputMode="decimal" suffix="mm" onChange={(e) => wizard.setZ0(e.target.value)} />
            <TextInput label={t('calibration.stereo.scale')} value={wizard.zScale} inputMode="decimal" onChange={(e) => wizard.setZScale(e.target.value)} />
          </div>
          <div className="grid grid-cols-4 gap-2">
            <TextInput label="X" value={String((wizard.roi as Extract<Region, { shape: 'rect' }>).x)} inputMode="decimal" onChange={(e) => wizard.setRoi({ ...(wizard.roi as Extract<Region, { shape: 'rect' }>), x: Number(e.target.value) || 0 })} />
            <TextInput label="Y" value={String((wizard.roi as Extract<Region, { shape: 'rect' }>).y)} inputMode="decimal" onChange={(e) => wizard.setRoi({ ...(wizard.roi as Extract<Region, { shape: 'rect' }>), y: Number(e.target.value) || 0 })} />
            <TextInput label="W" value={String((wizard.roi as Extract<Region, { shape: 'rect' }>).w)} inputMode="decimal" onChange={(e) => wizard.setRoi({ ...(wizard.roi as Extract<Region, { shape: 'rect' }>), w: Number(e.target.value) || 1 })} />
            <TextInput label="H" value={String((wizard.roi as Extract<Region, { shape: 'rect' }>).h)} inputMode="decimal" onChange={(e) => wizard.setRoi({ ...(wizard.roi as Extract<Region, { shape: 'rect' }>), h: Number(e.target.value) || 1 })} />
          </div>
          <Button variant="primary" loading={wizard.busy} disabled={!wizard.zAsset || !last?.left.ref || !last?.right.ref} onClick={() => void measureReference()} data-testid="calib-stereo-reference">
            {t('calibration.stereo.measureReference')}
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}

export function StereoResult({ stereo }: { stereo: StereoBlock }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-1 text-sm" data-testid="calib-stereo-result">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-xl font-semibold tabular-nums">{stereo.baseline_mm.toFixed(3)}</span>
        <span className="text-xs text-subtle">{t('calibration.stereo.baseline')}</span>
      </div>
      <p className="text-xs text-subtle">{t('calibration.stereo.rms', { rms: stereo.rms.toFixed(3) })}</p>
      {stereo.z_ref ? (
        <p className="text-xs text-subtle">{t('calibration.stereo.zRef', { d0: stereo.z_ref.d0_mm.toFixed(2), z0: stereo.z_ref.Z0_mm.toFixed(2), scale: stereo.z_ref.scale.toFixed(3) })}</p>
      ) : (
        <p className="text-xs text-warning">{t('calibration.stereo.noZRef')}</p>
      )}
    </div>
  )
}
