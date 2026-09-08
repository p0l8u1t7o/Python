/**
 * 多相機拼接精靈：選來源與標定，組出一條只含取像與 stitch_images 的流程。
 *
 * 設定保存於流程圖的 stitch_images 節點 params；來源保存於各 image_source 節點。
 * 這沿用既有流程版本、權限、試執行與配方能力，不需要新增資料表。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, Eye, Plus, Save, Trash2 } from 'lucide-react'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import {
  Badge, Button, Card, CardBody, CardHeader, EmptyState, IconButton, Modal,
  Select, TBody, THead, Table, Td, TextInput, Th, Tr,
} from '@/components/ui'
import { api, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { previewFlow, useAssets, useFlowMutations, useSources } from '@/lib/queries'
import type { FlowGraph, PreviewReport } from '@/lib/types'

type StitchMode = 'grid' | 'homography'
type StitchOrder = 'row_major' | 'column_major'
type StitchBlend = 'mean' | 'min' | 'max' | 'uncover'

interface StitchShot {
  ref: string
  width: number
  height: number
  name: string
}

interface StitchSlot {
  sourceId: string
  calibrationId: string
  shot: StitchShot | null
}

const BLENDS: StitchBlend[] = ['uncover', 'mean', 'min', 'max']

function emptySlot(): StitchSlot {
  return { sourceId: '', calibrationId: '', shot: null }
}

export function useStitchWizard() {
  const [slots, setSlots] = useState<StitchSlot[]>([emptySlot(), emptySlot()])
  const [mode, setMode] = useState<StitchMode>('grid')
  const [rows, setRows] = useState('1')
  const [cols, setCols] = useState('2')
  const [order, setOrder] = useState<StitchOrder>('row_major')
  const [trim, setTrim] = useState('0')
  const [overlapX, setOverlapX] = useState('0')
  const [overlapY, setOverlapY] = useState('0')
  const [blend, setBlend] = useState<StitchBlend>('uncover')
  const [scale, setScale] = useState('0')
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<PreviewReport | null>(null)
  const [flowId, setFlowId] = useState<number | null>(null)

  function reset() {
    setSlots([emptySlot(), emptySlot()])
    setPreview(null)
    setFlowId(null)
  }

  function updateSlot(index: number, patch: Partial<StitchSlot>) {
    setPreview(null)
    setSlots((prev) => prev.map((slot, i) => (i === index ? { ...slot, ...patch } : slot)))
  }

  function addSlot() {
    setPreview(null)
    setSlots((prev) => (prev.length >= 4 ? prev : [...prev, emptySlot()]))
  }

  function removeSlot(index: number) {
    setPreview(null)
    setSlots((prev) => (prev.length <= 2 ? prev : prev.filter((_, i) => i !== index)))
  }

  function params() {
    return {
      mode,
      rows: Number(rows) || 1,
      cols: Number(cols) || slots.length,
      order,
      trim: Number(trim) || 0,
      overlap_x: Number(overlapX) || 0,
      overlap_y: Number(overlapY) || 0,
      blend,
      scale: Number(scale) || 0,
      ...Object.fromEntries(slots.map((slot, i) => [`calibration_${i + 1}`, slot.calibrationId]).filter(([, value]) => value)),
    }
  }

  function graph(): FlowGraph {
    const nodes: FlowGraph['nodes'] = slots.map((slot, i) => ({
      id: `camera_${i + 1}`,
      type: 'image_source',
      label: `Camera ${i + 1}`,
      params: { source_id: Number(slot.sourceId), mode: 'source' },
      position: { x: 40, y: 40 + i * 110 },
    }))
    nodes.push({
      id: 'stitch',
      type: 'stitch_images',
      label: 'Stitch',
      params: params(),
      position: { x: 360, y: 120 },
    })
    return {
      nodes,
      edges: slots.map((_, i) => ({
        source: `camera_${i + 1}`,
        target: 'stitch',
        source_handle: 'image',
        target_handle: `image_${i + 1}`,
      })),
    }
  }

  const count = slots.length
  const gridReady = mode !== 'grid' || (Number(rows) || 0) * (Number(cols) || 0) === count
  const hasSources = slots.every((slot) => slot.sourceId)
  const hasCalibrations = mode !== 'homography' || slots.every((slot) => slot.calibrationId)
  const canPreview = count >= 2 && count <= 4 && hasSources && hasCalibrations && gridReady

  return {
    slots, mode, setMode, rows, setRows, cols, setCols, order, setOrder,
    trim, setTrim, overlapX, setOverlapX, overlapY, setOverlapY, blend, setBlend,
    scale, setScale, busy, setBusy, preview, setPreview, flowId, setFlowId,
    reset, updateSlot, addSlot, removeSlot, params, graph, canPreview, gridReady,
  }
}

type Wizard = ReturnType<typeof useStitchWizard>

interface Props {
  wizard: Wizard
  onError: (message: string) => void
  onSaved: (message: string) => void
}

export function StitchWizard({ wizard, onError, onSaved }: Props) {
  const { t } = useTranslation()
  const sources = useSources()
  const calibrations = useAssets('calibration')
  const flowMut = useFlowMutations()
  const [saveOpen, setSaveOpen] = useState(false)
  const [name, setName] = useState('')
  const sourceOptions = (sources.data?.items ?? []).map((s) => ({ value: String(s.id), label: s.name }))
  const calibrationOptions = (calibrations.data?.items ?? []).map((asset) => ({ value: String(asset.id), label: asset.name }))
  const previewRef = useMemo(() => {
    const value = wizard.preview?.nodes?.stitch?.outputs?.image
    return typeof value === 'string' ? value : ''
  }, [wizard.preview])
  const previewWidth = Number(wizard.preview?.nodes?.stitch?.outputs?.width ?? 0)
  const previewHeight = Number(wizard.preview?.nodes?.stitch?.outputs?.height ?? 0)
  const defaultName = t('calibration.stitch.defaultName')

  async function capture(index: number) {
    const sourceId = wizard.slots[index]?.sourceId
    if (!sourceId) return
    wizard.setBusy(true)
    try {
      const shot = await api.post<StitchShot>('/vision/calibration/capture', {}, { source_id: Number(sourceId) })
      wizard.updateSlot(index, { shot })
    } catch (err) {
      onError(errorMessage(err))
    } finally {
      wizard.setBusy(false)
    }
  }

  async function ensureFlow(graph: FlowGraph) {
    if (wizard.flowId) return wizard.flowId
    const flow = await flowMut.create.mutateAsync({
      name: t('calibration.stitch.previewFlowName'),
      description: t('calibration.stitch.description'),
      graph,
    })
    wizard.setFlowId(flow.id)
    return flow.id
  }

  async function preview() {
    if (!wizard.canPreview) return
    wizard.setBusy(true)
    try {
      const graph = wizard.graph()
      const flowId = await ensureFlow(graph)
      const report = await previewFlow({ flowId, graph, until_node: 'stitch' })
      wizard.setPreview(report)
      if (report.nodes?.stitch?.status !== 'ok') onError(report.nodes?.stitch?.message || report.error || t('errors.validation_error'))
    } catch (err) {
      onError(errorMessage(err))
    } finally {
      wizard.setBusy(false)
    }
  }

  async function save() {
    const graph = wizard.graph()
    wizard.setBusy(true)
    try {
      if (wizard.flowId) {
        await flowMut.patch.mutateAsync({ id: wizard.flowId, name: name.trim() || defaultName, description: t('calibration.stitch.description'), graph })
      } else {
        const flow = await flowMut.create.mutateAsync({ name: name.trim() || defaultName, description: t('calibration.stitch.description'), graph })
        wizard.setFlowId(flow.id)
      }
      setSaveOpen(false)
      onSaved(t('calibration.stitch.saved', { name: name.trim() || defaultName }))
    } catch (err) {
      onError(errorMessage(err))
    } finally {
      wizard.setBusy(false)
    }
  }

  function slotRow(slot: StitchSlot, index: number) {
    return (
      <Tr key={index} testId={`calib-stitch-slot-${index}`}>
        <Td>{index + 1}</Td>
        <Td>
          <Select
            value={slot.sourceId}
            onChange={(e) => wizard.updateSlot(index, { sourceId: e.target.value, shot: null })}
            placeholder={t('calibration.pickSource')}
            options={sourceOptions}
            data-testid={`calib-stitch-source-${index}`}
          />
        </Td>
        <Td>
          <Select
            value={slot.calibrationId}
            onChange={(e) => wizard.updateSlot(index, { calibrationId: e.target.value })}
            placeholder={t('calibration.stitch.pickCalibration')}
            options={calibrationOptions}
            data-testid={`calib-stitch-calibration-${index}`}
          />
        </Td>
        <Td>{slot.shot ? `${slot.shot.width}x${slot.shot.height}` : '-'}</Td>
        <Td align="right">
          <div className="flex justify-end gap-1">
            <IconButton label={t('calibration.capture')} disabled={!slot.sourceId || wizard.busy} onClick={() => void capture(index)}>
              <Camera size={13} />
            </IconButton>
            <IconButton label={t('common.delete')} disabled={wizard.slots.length <= 2} onClick={() => wizard.removeSlot(index)}>
              <Trash2 size={13} />
            </IconButton>
          </div>
        </Td>
      </Tr>
    )
  }

  return (
    <div className="space-y-4" data-testid="calib-stitch-wizard">
      <Card>
        <CardHeader
          title={t('calibration.stitch.title')}
          actions={
            <Button icon={<Plus size={14} />} disabled={wizard.slots.length >= 4} onClick={wizard.addSlot}>
              {t('calibration.stitch.addCamera')}
            </Button>
          }
        />
        <CardBody className="space-y-3">
          <Table>
            <THead>
              <Th>#</Th>
              <Th>{t('calibration.pickSource')}</Th>
              <Th>{t('calibration.stitch.calibration')}</Th>
              <Th>{t('calibration.stitch.shot')}</Th>
              <Th />
            </THead>
            <TBody>{wizard.slots.map(slotRow)}</TBody>
          </Table>
          <div className="grid gap-3 md:grid-cols-3">
            {wizard.slots.map((slot, index) => (
              <div key={index} className="min-h-0">
                {slot.shot ? (
                  <ImageViewer
                    src={imageUrl(slot.shot.ref, 600)}
                    imageWidth={slot.shot.width}
                    imageHeight={slot.shot.height}
                    className="h-[180px]"
                    stateKey={`calibration:stitch:${index}`}
                  />
                ) : (
                  <EmptyState title={t('calibration.stitch.noShot')} description={t('calibration.stitch.captureHint')} icon={<Camera size={22} />} />
                )}
              </div>
            ))}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t('calibration.stitch.settings')} />
        <CardBody className="space-y-3">
          <div className="grid gap-2 md:grid-cols-4">
            <Select
              label={t('calibration.stitch.mode')}
              value={wizard.mode}
              onChange={(e) => { wizard.setMode(e.target.value as StitchMode); wizard.setPreview(null) }}
              options={(['grid', 'homography'] as StitchMode[]).map((value) => ({ value, label: t(`calibration.stitch.modes.${value}`) }))}
            />
            <Select
              label={t('calibration.stitch.blend')}
              value={wizard.blend}
              onChange={(e) => { wizard.setBlend(e.target.value as StitchBlend); wizard.setPreview(null) }}
              options={BLENDS.map((value) => ({ value, label: t(`calibration.stitch.blends.${value}`) }))}
            />
            <TextInput label={t('calibration.rows')} value={wizard.rows} inputMode="numeric" disabled={wizard.mode !== 'grid'} onChange={(e) => { wizard.setRows(e.target.value); wizard.setPreview(null) }} />
            <TextInput label={t('calibration.cols')} value={wizard.cols} inputMode="numeric" disabled={wizard.mode !== 'grid'} onChange={(e) => { wizard.setCols(e.target.value); wizard.setPreview(null) }} />
            <Select
              label={t('calibration.stitch.order')}
              value={wizard.order}
              disabled={wizard.mode !== 'grid'}
              onChange={(e) => { wizard.setOrder(e.target.value as StitchOrder); wizard.setPreview(null) }}
              options={(['row_major', 'column_major'] as StitchOrder[]).map((value) => ({ value, label: t(`calibration.stitch.orders.${value}`) }))}
            />
            <TextInput label={t('calibration.stitch.trim')} value={wizard.trim} inputMode="numeric" disabled={wizard.mode !== 'grid'} suffix="px" onChange={(e) => { wizard.setTrim(e.target.value); wizard.setPreview(null) }} />
            <TextInput label={t('calibration.stitch.overlapX')} value={wizard.overlapX} inputMode="numeric" disabled={wizard.mode !== 'grid'} suffix="px" onChange={(e) => { wizard.setOverlapX(e.target.value); wizard.setPreview(null) }} />
            <TextInput label={t('calibration.stitch.overlapY')} value={wizard.overlapY} inputMode="numeric" disabled={wizard.mode !== 'grid'} suffix="px" onChange={(e) => { wizard.setOverlapY(e.target.value); wizard.setPreview(null) }} />
            <TextInput label={t('calibration.stitch.scale')} value={wizard.scale} inputMode="decimal" disabled={wizard.mode !== 'homography'} onChange={(e) => { wizard.setScale(e.target.value); wizard.setPreview(null) }} />
          </div>
          {!wizard.gridReady ? <p className="text-xs text-warning">{t('calibration.stitch.gridMismatch')}</p> : null}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={<Eye size={14} />} loading={wizard.busy} disabled={!wizard.canPreview} onClick={() => void preview()} data-testid="calib-stitch-preview">
              {t('calibration.stitch.preview')}
            </Button>
            <Button icon={<Save size={14} />} disabled={!wizard.canPreview} onClick={() => { setName(name || defaultName); setSaveOpen(true) }} data-testid="calib-stitch-save">
              {t('calibration.stitch.save')}
            </Button>
            {wizard.flowId ? <Badge tone="neutral">{t('calibration.stitch.flowId', { id: wizard.flowId })}</Badge> : null}
          </div>
          <p className="text-xs text-subtle">{t('calibration.stitch.storeHint')}</p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t('calibration.stitch.previewResult')} />
        <CardBody>
          {previewRef && previewWidth > 0 && previewHeight > 0 ? (
            <ImageViewer
              src={imageUrl(previewRef, 1600)}
              imageWidth={previewWidth}
              imageHeight={previewHeight}
              className="h-[360px]"
              stateKey="calibration:stitch:preview"
            />
          ) : (
            <EmptyState title={t('calibration.stitch.noPreview')} description={t('calibration.stitch.previewHint')} icon={<Eye size={22} />} />
          )}
        </CardBody>
      </Card>

      <Modal open={saveOpen} onClose={() => setSaveOpen(false)} title={t('calibration.stitch.save')}>
        <div className="space-y-3">
          <TextInput label={t('common.name')} value={name} onChange={(e) => setName(e.target.value)} data-testid="calib-stitch-save-name" />
          <p className="text-xs text-subtle">{t('calibration.stitch.storeHint')}</p>
          <div className="flex justify-end gap-2">
            <Button onClick={() => setSaveOpen(false)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={wizard.busy} disabled={!wizard.canPreview} onClick={() => void save()} data-testid="calib-stitch-save-confirm">
              {t('common.save')}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
