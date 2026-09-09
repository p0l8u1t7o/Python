/**
 * 手眼標定精靈：機構到位 → 取像 → 定位特徵 → 記錄一點，湊滿三點以上就解得出來。
 *
 * 狀態全住在 useRobotWizard 裡，標定頁只要把畫面上的點擊轉給 pick()、把 overlays 畫出來、
 * 把 body() 送去 solve——那一頁不必為了第四種模式再長一倍。
 * 平移與旋轉刻意分兩次採集：拿平移走的點去擬旋轉中心是錯的，量的是兩件事。
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Crosshair, Trash2 } from 'lucide-react'
import {
  Badge, Button, Card, CardBody, CardHeader, Checkbox, EmptyRow, IconButton,
  Select, TBody, THead, Table, Td, TextInput, Th, Tr,
} from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { previewFlow, useCalibrationRobotSignals, useFlow, useFlows } from '@/lib/queries'
import type { CalibrationSignal, Overlay } from '@/lib/types'

export type RobotKind = 'translation' | 'translation_rotation'
export type CameraMode = 'fixed' | 'moving'
type Stage = 'translation' | 'rotation'
type Locate = 'click' | 'flow'
type CoordinateSource = 'manual' | 'connection'

interface RobotPoint {
  px: [number, number]
  /** 機構回報的座標，保持字串：現場邊填邊看，空欄位不該被當成 0 */
  robot: [string, string]
  error: number | null
}

interface RotationPoint {
  px: [number, number]
  r?: string
  error: number | null
}

/** 已解出的機構區塊（solve 回來的 payload.robot） */
export interface RobotBlock {
  matrix: number[][]
  kind: string
  camera_mode: string
  handedness: 'left' | 'right'
  angle_sign: number
  rms: number
  max_error: number
  points: { error: number }[]
  rotation_center_px?: number[]
  rotation_rms_px?: number
  rotation_max_error_px?: number
  rotation_points?: { error: number }[]
}

const MAX_POINTS = 200

/** 節點輸出裡的一個像素點：範本比對、形狀比對、找圓、Blob 的命名都不一樣，照常見順序找。 */
export function pointOf(outputs: Record<string, unknown> | undefined): [number, number] | null {
  if (!outputs) return null
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
  for (const [kx, ky] of [['best_x', 'best_y'], ['cx', 'cy'], ['x', 'y'], ['center_x', 'center_y']]) {
    const x = num(outputs[kx])
    const y = num(outputs[ky])
    if (x != null && y != null) return [x, y]
  }
  const centre = outputs.center ?? outputs.centre
  if (Array.isArray(centre) && centre.length >= 2) {
    const x = num(centre[0])
    const y = num(centre[1])
    if (x != null && y != null) return [x, y]
  }
  const first = Array.isArray(outputs.matches) ? (outputs.matches[0] as Record<string, unknown> | undefined) : undefined
  if (first) {
    const x = num(first.cx ?? first.x)
    const y = num(first.cy ?? first.y)
    if (x != null && y != null) return [x, y]
  }
  return null
}

export function useRobotWizard(shotRef: string | null) {
  const [kind, setKind] = useState<RobotKind>('translation')
  const [cameraMode, setCameraMode] = useState<CameraMode>('fixed')
  const [stage, setStage] = useState<Stage>('translation')
  const [next, setNext] = useState<[string, string]>(['', ''])
  const [points, setPoints] = useState<RobotPoint[]>([])
  const [rotation, setRotation] = useState<RotationPoint[]>([])
  const [coordinateSource, setCoordinateSource] = useState<CoordinateSource>('manual')
  const [signalSeq, setSignalSeq] = useState(0)
  const [receivedCount, setReceivedCount] = useState(0)
  const [lastSignal, setLastSignal] = useState<CalibrationSignal | null>(null)
  const [connectionEnded, setConnectionEnded] = useState(false)
  const [teachSignal, setTeachSignal] = useState<CalibrationSignal | null>(null)
  const [rotationR, setRotationR] = useState('')
  const [locate, setLocate] = useState<Locate>('click')
  const [flowId, setFlowId] = useState('')
  const [nodeId, setNodeId] = useState('')
  const [locating, setLocating] = useState(false)
  const [located, setLocated] = useState('')
  const flow = useFlow(locate === 'flow' && flowId ? Number(flowId) : null)

  function record(px: [number, number]) {
    if (stage === 'rotation') {
      setRotation((prev) => (prev.length >= MAX_POINTS ? prev : [...prev, { px, r: rotationR, error: null }]))
      return
    }
    setPoints((prev) => (prev.length >= MAX_POINTS ? prev : [...prev, { px, robot: [next[0], next[1]], error: null }]))
  }

  function consumeSignals(items: CalibrationSignal[], lastSeq: number): boolean {
    if (lastSeq > signalSeq) setSignalSeq(lastSeq)
    if (!items.length) return false
    let dirty = false
    for (const item of items) {
      setLastSignal(item)
      if (item.kind === 'start') {
        setPoints([])
        setRotation([])
        setStage('translation')
        setReceivedCount(0)
        setConnectionEnded(false)
        setTeachSignal(null)
        setRotationR('')
        dirty = true
      } else if (item.kind === 'point') {
        setReceivedCount((prev) => prev + 1)
        setConnectionEnded(false)
        if (stage === 'rotation') {
          const rText = item.r == null ? '' : String(item.r)
          setRotationR(rText)
          setRotation((prev) => {
            const index = prev.findIndex((point) => !point.r)
            if (index < 0) return prev
            dirty = true
            return prev.map((point, i) => (i === index ? { ...point, r: rText } : point))
          })
        } else if (item.x != null && item.y != null) {
          const robot: [string, string] = [String(item.x), String(item.y)]
          setNext(robot)
          setPoints((prev) => {
            const index = prev.findIndex((point) => point.robot[0].trim() === '' || point.robot[1].trim() === '')
            if (index < 0) return prev
            dirty = true
            return prev.map((point, i) => (i === index ? { ...point, robot } : point))
          })
        }
        dirty = true
      } else if (item.kind === 'end') {
        setConnectionEnded(true)
      } else if (item.kind === 'teach') {
        setTeachSignal(item)
      }
    }
    return dirty
  }

  /** 用一條流程定位這一張的特徵：試跑到選定的節點，取它輸出的點。 */
  async function locateWithFlow(): Promise<string> {
    if (!shotRef || !flow.data || !nodeId) return ''
    setLocating(true)
    setLocated('')
    try {
      const report = await previewFlow({ flowId: flow.data.id, graph: flow.data.graph, reuse_image_ref: shotRef, until_node: nodeId })
      const px = pointOf(report.nodes?.[nodeId]?.outputs)
      if (!px) return 'no_point'
      record(px)
      setLocated(`${px[0].toFixed(1)}, ${px[1].toFixed(1)}`)
      return ''
    } catch (err) {
      return errorMessage(err)
    } finally {
      setLocating(false)
    }
  }

  function reset() {
    setPoints([])
    setRotation([])
    setStage('translation')
    setLocated('')
    setReceivedCount(0)
    setConnectionEnded(false)
    setTeachSignal(null)
    setRotationR('')
  }

  const filled = points.every((p) => p.robot[0].trim() !== '' && p.robot[1].trim() !== '')
  const canSolve = points.length >= 3 && filled && (kind === 'translation' || rotation.length >= 3)

  /** solve 的請求主體。平移點是四個純量欄位，與 mode="points" 的 px:[x,y] 不一樣。 */
  function body() {
    return {
      mode: 'robot',
      kind,
      camera_mode: cameraMode,
      points: points.map((p) => ({ px: p.px[0], py: p.px[1], rx: Number(p.robot[0]), ry: Number(p.robot[1]) })),
      rotation_points: kind === 'translation_rotation' ? rotation.map((p) => p.px) : [],
    }
  }

  /** 解完把逐點殘差填回表格（最大的那一點在畫面上會標紅）。 */
  function applyResult(robot: RobotBlock | null) {
    setPoints((prev) => prev.map((p, i) => ({ ...p, error: robot?.points?.[i]?.error ?? null })))
    setRotation((prev) => prev.map((p, i) => ({ ...p, error: robot?.rotation_points?.[i]?.error ?? null })))
  }

  const overlays = useMemo<Overlay[]>(() => {
    const worst = points.reduce((m, p) => Math.max(m, p.error ?? 0), 0)
    const marks = points.map((p, i) => ({
      kind: 'point', x: p.px[0], y: p.px[1],
      color: p.error != null && worst > 0 && p.error >= worst ? '#ef4444' : '#22c55e',
      label: p.error != null ? `${i + 1}: ${p.error.toFixed(3)}` : String(i + 1),
    } as Overlay))
    const arc = rotation.map((p, i) => ({ kind: 'point', x: p.px[0], y: p.px[1], color: '#38bdf8', label: `R${i + 1}` } as Overlay))
    return [...marks, ...arc]
  }, [points, rotation])

  return {
    kind, setKind, cameraMode, setCameraMode, stage, setStage, next, setNext,
    points, setPoints, rotation, setRotation, coordinateSource, setCoordinateSource,
    signalSeq, receivedCount, lastSignal, connectionEnded, teachSignal, rotationR,
    locate, setLocate,
    flowId, setFlowId, nodeId, setNodeId, locating, located, flow,
    record, locateWithFlow, reset, consumeSignals, canSolve, body, applyResult, overlays,
  }
}

type Wizard = ReturnType<typeof useRobotWizard>

interface Props {
  wizard: Wizard
  unit: string
  snap: boolean
  onSnap: (value: boolean) => void
  hasPicture: boolean
  onChange: () => void
  onLocateError: (message: string) => void
}

/** 右側面板：三個步驟、平移與旋轉兩張表。 */
export function RobotWizard({ wizard, unit, snap, onSnap, hasPicture, onChange, onLocateError }: Props) {
  const { t } = useTranslation()
  const flows = useFlows()
  const rotating = wizard.kind === 'translation_rotation'
  const signals = useCalibrationRobotSignals(wizard.signalSeq, wizard.coordinateSource === 'connection')
  // graph.nodes 是陣列不是字典：值要用節點 id，until_node 與報告的 nodes[] 都靠它
  const nodes = (wizard.flow.data?.graph?.nodes ?? [])
    .filter((n) => n.type !== 'note' && n.type !== 'image_source')
    .map((n) => ({ value: n.id, label: `${n.id} (${n.type})` }))
  const steps = [
    { key: 'move', done: wizard.next[0].trim() !== '' && wizard.next[1].trim() !== '' },
    { key: 'grab', done: hasPicture },
    { key: 'mark', done: wizard.points.length > 0 },
  ]

  function update<T>(setter: (value: T) => void, value: T) {
    setter(value)
    onChange()
  }

  useEffect(() => {
    if (!signals.data) return
    if (wizard.consumeSignals(signals.data.items, signals.data.last_seq)) onChange()
  }, [signals.data])

  return (
    <Card>
      <CardHeader title={t('calibration.robot.title')} />
      <CardBody className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <Select
            label={t('calibration.robot.kind')}
            value={wizard.kind}
            onChange={(e) => update(wizard.setKind, e.target.value as RobotKind)}
            options={(['translation', 'translation_rotation'] as RobotKind[]).map((k) => ({ value: k, label: t(`calibration.robot.kinds.${k}`) }))}
            data-testid="calib-robot-kind"
          />
          <Select
            label={t('calibration.robot.cameraMode')}
            value={wizard.cameraMode}
            onChange={(e) => update(wizard.setCameraMode, e.target.value as CameraMode)}
            options={(['fixed', 'moving'] as CameraMode[]).map((k) => ({ value: k, label: t(`calibration.robot.cameraModes.${k}`) }))}
            hint={t(`calibration.robot.cameraModeHints.${wizard.cameraMode}`)}
            data-testid="calib-robot-camera"
          />
        </div>

        <ol className="space-y-1 text-xs" data-testid="calib-robot-steps">
          {steps.map((step, i) => (
            <li key={step.key} className="flex gap-2">
              <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] ${step.done ? 'bg-brand text-white' : 'bg-line text-subtle'}`}>{i + 1}</span>
              <span className={step.done ? 'text-subtle' : ''}>{t(`calibration.robot.steps.${step.key}`)}</span>
            </li>
          ))}
        </ol>

        {rotating ? (
          <div className="flex gap-2" data-testid="calib-robot-stage">
            {(['translation', 'rotation'] as Stage[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => wizard.setStage(s)}
                className={`flex-1 rounded-md border px-2 py-1 text-xs transition ${wizard.stage === s ? 'border-brand bg-brand/5 font-medium' : 'border-line text-subtle hover:border-brand/40'}`}
                data-testid={`calib-robot-stage-${s}`}
              >
                {t(`calibration.robot.stages.${s}`)}
                <span className="ml-1 tabular-nums">{s === 'translation' ? wizard.points.length : wizard.rotation.length}</span>
              </button>
            ))}
          </div>
        ) : null}

        <Select
          label={t('calibration.robot.coordSource')}
          value={wizard.coordinateSource}
          onChange={(e) => update(wizard.setCoordinateSource, e.target.value as CoordinateSource)}
          options={(['manual', 'connection'] as CoordinateSource[]).map((source) => ({ value: source, label: t(`calibration.robot.coordSources.${source}`) }))}
          hint={t(`calibration.robot.coordSourceHints.${wizard.coordinateSource}`)}
          data-testid="calib-robot-coord-source"
        />

        {wizard.coordinateSource === 'connection' ? (
          <div className="space-y-1 rounded-md border border-line bg-panel/40 p-2 text-xs" data-testid="calib-robot-connection">
            <p className="text-subtle">{t('calibration.robot.connectionSetup')}</p>
            <p>{t('calibration.robot.received', { n: wizard.receivedCount })}</p>
            {wizard.connectionEnded ? <p className="text-brand">{t('calibration.robot.connectionEnd')}</p> : null}
            {wizard.teachSignal ? (
              <p className="text-subtle">{t('calibration.robot.teachPoint', {
                x: wizard.teachSignal.x ?? '', y: wizard.teachSignal.y ?? '', r: wizard.teachSignal.r ?? '',
              })}</p>
            ) : null}
            {wizard.lastSignal ? (
              <p className="break-words text-subtle" title={wizard.lastSignal.source}>
                {t('calibration.robot.lastSignal', {
                  kind: t(`integration.rules.signalKinds.${wizard.lastSignal.kind}`),
                  time: new Date(wizard.lastSignal.ts * 1000).toLocaleTimeString(),
                  source: wizard.lastSignal.source || '-',
                })}
              </p>
            ) : null}
          </div>
        ) : null}

        {wizard.stage === 'translation' && wizard.coordinateSource === 'manual' ? (
          <div className="grid grid-cols-2 gap-2">
            <TextInput
              label={`${t('calibration.robot.nextX')} (${unit})`}
              value={wizard.next[0]}
              inputMode="decimal"
              onChange={(e) => wizard.setNext([e.target.value, wizard.next[1]])}
              data-testid="calib-robot-next-x"
            />
            <TextInput
              label={`${t('calibration.robot.nextY')} (${unit})`}
              value={wizard.next[1]}
              inputMode="decimal"
              onChange={(e) => wizard.setNext([wizard.next[0], e.target.value])}
              data-testid="calib-robot-next-y"
            />
          </div>
        ) : wizard.stage === 'rotation' ? (
          <div className="space-y-1 text-xs text-subtle" data-testid="calib-robot-rotation-hint">
            <p>{t('calibration.robot.rotationHint')}</p>
            {wizard.coordinateSource === 'connection' && wizard.rotationR ? <p>{`${t('calibration.robot.rotationAngle')}: ${wizard.rotationR}`}</p> : null}
          </div>
        ) : null}

        <Select
          label={t('calibration.robot.locate')}
          value={wizard.locate}
          onChange={(e) => wizard.setLocate(e.target.value as Locate)}
          options={(['click', 'flow'] as Locate[]).map((k) => ({ value: k, label: t(`calibration.robot.locates.${k}`) }))}
          hint={t(`calibration.robot.locateHints.${wizard.locate}`)}
          data-testid="calib-robot-locate"
        />
        {wizard.locate === 'click' ? (
          <Checkbox label={t('calibration.snap')} hint={t('calibration.snapHint')} checked={snap} onChange={onSnap} />
        ) : (
          <div className="space-y-2">
            <Select
              value={wizard.flowId}
              onChange={(e) => { wizard.setFlowId(e.target.value); wizard.setNodeId('') }}
              placeholder={t('calibration.robot.pickFlow')}
              options={(flows.data?.items ?? []).map((f) => ({ value: String(f.id), label: f.name }))}
              data-testid="calib-robot-flow"
            />
            <Select
              value={wizard.nodeId}
              onChange={(e) => wizard.setNodeId(e.target.value)}
              placeholder={t('calibration.robot.pickNode')}
              options={nodes}
              data-testid="calib-robot-node"
            />
            <Button
              icon={<Crosshair size={14} />}
              loading={wizard.locating}
              disabled={!hasPicture || !wizard.nodeId}
              onClick={() => { void wizard.locateWithFlow().then((err) => { if (err) onLocateError(err === 'no_point' ? t('calibration.robot.noPoint') : err); else onChange() }) }}
              data-testid="calib-robot-run-locate"
            >
              {t('calibration.robot.runLocate')}
            </Button>
            {wizard.located ? <p className="text-xs text-subtle" data-testid="calib-robot-located">{t('calibration.robot.located', { point: wizard.located })}</p> : null}
          </div>
        )}

        {wizard.stage === 'translation' ? (
          <Table>
            <THead>
              <Th>#</Th>
              <Th>{t('calibration.pixel')}</Th>
              <Th>{`X (${unit})`}</Th>
              <Th>{`Y (${unit})`}</Th>
              <Th align="right">{t('calibration.pointError')}</Th>
              <Th /></THead>
            <TBody>
              {wizard.points.length ? wizard.points.map((p, i) => (
                <Tr key={`${p.px[0]}-${p.px[1]}-${i}`} testId={`calib-robot-point-${i}`}>
                  <Td>{i + 1}</Td>
                  <Td className="whitespace-nowrap">{`${p.px[0].toFixed(1)}, ${p.px[1].toFixed(1)}`}</Td>
                  <Td>
                    <TextInput
                      value={p.robot[0]}
                      className="w-20 px-2"
                      inputMode="decimal"
                      onChange={(e) => { wizard.setPoints((prev) => prev.map((q, j) => (j === i ? { ...q, robot: [e.target.value, q.robot[1]] } : q))); onChange() }}
                      data-testid={`calib-robot-x-${i}`}
                    />
                  </Td>
                  <Td>
                    <TextInput
                      value={p.robot[1]}
                      className="w-20 px-2"
                      inputMode="decimal"
                      onChange={(e) => { wizard.setPoints((prev) => prev.map((q, j) => (j === i ? { ...q, robot: [q.robot[0], e.target.value] } : q))); onChange() }}
                      data-testid={`calib-robot-y-${i}`}
                    />
                  </Td>
                  <Td align="right">{p.error == null ? '—' : p.error.toFixed(3)}</Td>
                  <Td align="right">
                    <IconButton label={t('common.delete')} onClick={() => { wizard.setPoints((prev) => prev.filter((_, j) => j !== i)); onChange() }}>
                      <Trash2 size={13} />
                    </IconButton>
                  </Td>
                </Tr>
              )) : <EmptyRow colSpan={6} message={t('calibration.robot.noPoints')} />}
            </TBody>
          </Table>
        ) : (
          <Table>
            <THead>
              <Th>#</Th>
              <Th>{t('calibration.pixel')}</Th>
              <Th>{t('calibration.robot.rotationAngle')}</Th>
              <Th align="right">{t('calibration.robot.radialError')}</Th>
              <Th /></THead>
            <TBody>
              {wizard.rotation.length ? wizard.rotation.map((p, i) => (
                <Tr key={`${p.px[0]}-${p.px[1]}-${i}`} testId={`calib-robot-rot-${i}`}>
                  <Td>{`R${i + 1}`}</Td>
                  <Td>{`${p.px[0].toFixed(1)}, ${p.px[1].toFixed(1)}`}</Td>
                  <Td>{p.r || '—'}</Td>
                  <Td align="right">{p.error == null ? '—' : `${p.error.toFixed(3)} px`}</Td>
                  <Td align="right">
                    <IconButton label={t('common.delete')} onClick={() => { wizard.setRotation((prev) => prev.filter((_, j) => j !== i)); onChange() }}>
                      <Trash2 size={13} />
                    </IconButton>
                  </Td>
                </Tr>
              )) : <EmptyRow colSpan={5} message={t('calibration.robot.noRotation')} />}
            </TBody>
          </Table>
        )}

        {wizard.points.length && !wizard.canSolve ? (
          <p className="text-xs text-warning" data-testid="calib-robot-need">
            {wizard.points.length < 3
              ? t('calibration.robot.needPoints', { n: 3 - wizard.points.length })
              : rotating && wizard.rotation.length < 3
                ? t('calibration.robot.needRotation', { n: 3 - wizard.rotation.length })
                : t('calibration.robot.needCoords')}
          </p>
        ) : null}
      </CardBody>
    </Card>
  )
}

/** 結果卡上機構專屬的那幾行（手性、角度正負、旋轉中心）。 */
export function RobotResult({ robot, unit }: { robot: RobotBlock; unit: string }) {
  const { t } = useTranslation()
  const matrix = robot.matrix
  const precision = Math.sqrt(Math.abs(matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]))
  return (
    <div className="space-y-1 text-sm" data-testid="calib-robot-result">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-xl font-semibold tabular-nums">{robot.rms.toFixed(4)}</span>
        <span className="text-xs text-subtle">{`${unit} ${t('calibration.robot.rms')}`}</span>
        <Badge tone={robot.handedness === 'right' ? 'neutral' : 'warning'}>{t(`calibration.robot.handedness.${robot.handedness}`)}</Badge>
        <Badge tone="neutral">{t('calibration.robot.angleSign', { sign: robot.angle_sign > 0 ? '+1' : '-1' })}</Badge>
      </div>
      <p className="text-xs text-subtle">{t('calibration.fitError', { rms: robot.rms.toFixed(3), max: robot.max_error.toFixed(3), unit })}</p>
      <p className="text-xs text-subtle" data-testid="calib-robot-precision">
        {t('calibration.robot.precision', { value: Number(precision.toPrecision(6)).toString(), unit })}
      </p>
      {robot.rotation_center_px ? (
        <p className="text-xs text-subtle" data-testid="calib-robot-center">
          {t('calibration.robot.center', {
            x: robot.rotation_center_px[0].toFixed(1), y: robot.rotation_center_px[1].toFixed(1),
            rms: (robot.rotation_rms_px ?? 0).toFixed(3),
          })}
        </p>
      ) : null}
    </div>
  )
}
