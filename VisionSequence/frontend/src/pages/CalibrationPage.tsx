/**
 * 標定頁：教平台「一個像素是多少毫米」與「鏡頭把畫面拱成什麼樣」，存成一個標定資產給工具用。
 *
 * 六種做法一頁到底，差別只在右邊面板：標定板、對點、距離、手眼、相機映射、拼接設定。
 * 刻意先算再存——殘差先給人看，覺得哪一點或哪一張不對可以刪掉重算，滿意了才存成資產。
 */
import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import i18next, { type Language } from '@/i18n'
import { localiseDataName } from '@/lib/catalogueLocale'
import { ArrowRightLeft, Camera, Crosshair, Download, Layers3, Move, PanelsTopLeft, Ruler, Save, Trash2, Upload, Wand2 } from 'lucide-react'
import { Page } from '@/components/layout/AppShell'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import {
  Badge, Button, Card, CardBody, CardHeader, Checkbox, EmptyRow, EmptyState, IconButton, Modal,
  PageHeader, Select, TBody, THead, Table, Td, TextInput, Th, Tr,
} from '@/components/ui'
import { RobotResult, RobotWizard, useRobotWizard } from '@/components/calibration/RobotWizard'
import type { RobotBlock } from '@/components/calibration/RobotWizard'
import { MappingResult, MappingWizard, useMappingWizard } from '@/components/calibration/MappingWizard'
import type { MappingBlock } from '@/components/calibration/MappingWizard'
import { StereoResult, StereoWizard, useStereoWizard } from '@/components/calibration/StereoWizard'
import type { StereoBlock } from '@/components/calibration/StereoWizard'
import { StitchWizard, useStitchWizard } from '@/components/calibration/StitchWizard'
import { BASE_URL, api, downloadFile, imageUrl, withKey } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useAssets, useSources } from '@/lib/queries'
import type { CalibrationSolveResult, Overlay } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

type Mode = 'board' | 'points' | 'distance' | 'robot' | 'mapping' | 'stereo' | 'stitch'
type BoardKind = 'chessboard' | 'circles' | 'acircles'
type BoardPattern = 'chessboard' | 'acircles'
type WorldKind = 'affine' | 'perspective' | 'scale'

interface Shot {
  ref: string
  width: number
  height: number
  name: string
  corners: number[][] | null
  overlays: Overlay[]
  hint: string
  error: number | null
}

interface MarkedPoint {
  px: [number, number]
  world: [string, string]
  error: number | null
}

type SolveResult = CalibrationSolveResult

const COVERAGE_COLS = 4
const COVERAGE_ROWS = 3
const RMS_WARN_PX = 0.5

/** 已採集角點的視野覆蓋率：4×3 格，沒角點的格子（多在邊角）就是畸變估不準的地方。純函式，與後端 calib.coverage 同一套格子。 */
function coverageOf(views: number[][][], width: number, height: number) {
  const grid = Array.from({ length: COVERAGE_ROWS }, () => new Array<number>(COVERAGE_COLS).fill(0))
  for (const view of views) {
    for (const [x, y] of view) {
      const cx = Math.min(COVERAGE_COLS - 1, Math.max(0, Math.floor((x * COVERAGE_COLS) / Math.max(1, width))))
      const cy = Math.min(COVERAGE_ROWS - 1, Math.max(0, Math.floor((y * COVERAGE_ROWS) / Math.max(1, height))))
      grid[cy][cx] += 1
    }
  }
  const missing: { col: number; row: number }[] = []
  grid.forEach((row, r) => row.forEach((n, c) => { if (n === 0) missing.push({ col: c, row: r }) }))
  const edgeMissing = missing.filter((m) => m.col === 0 || m.col === COVERAGE_COLS - 1 || m.row === 0 || m.row === COVERAGE_ROWS - 1).length
  return { grid, missing, covered: COVERAGE_COLS * COVERAGE_ROWS - missing.length, cells: COVERAGE_COLS * COVERAGE_ROWS, edgeMissing }
}

interface WorldBlock {
  kind: string
  mm_per_px: number
  rms: number
  max_error: number
  points?: { error: number }[]
}

interface LensBlock {
  rms: number
  views: number
  view_errors: number[]
}

const UNITS = [{ value: 'mm', key: 'mm' }, { value: 'um', key: 'um' }, { value: 'in', key: 'inch' }] as const
const QUALITY_TONE: Record<string, 'ok' | 'warning' | 'critical'> = { good: 'ok', fair: 'warning', poor: 'critical' }

function worldOf(result: SolveResult | null): WorldBlock | null {
  return (result?.payload?.world as WorldBlock | undefined) ?? null
}

function lensOf(result: SolveResult | null): LensBlock | null {
  return (result?.payload?.lens as LensBlock | undefined) ?? null
}

export function CalibrationPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const sources = useSources()
  const calibrations = useAssets('calibration')
  const fileInput = useRef<HTMLInputElement>(null)

  const [mode, setMode] = useState<Mode>('board')
  const [sourceId, setSourceId] = useState('')
  const [busy, setBusy] = useState(false)
  const [shots, setShots] = useState<Shot[]>([])
  const [showCoverage, setShowCoverage] = useState(true)
  const [current, setCurrent] = useState(0)
  const [boardKind, setBoardKind] = useState<BoardKind>('chessboard')
  const [cols, setCols] = useState('9')
  const [rows, setRows] = useState('6')
  const [spacing, setSpacing] = useState('5')
  const [unit, setUnit] = useState('mm')
  const [points, setPoints] = useState<MarkedPoint[]>([])
  const [worldKind, setWorldKind] = useState<WorldKind>('affine')
  const [snap, setSnap] = useState(true)
  const [distance, setDistance] = useState('10')
  const [result, setResult] = useState<SolveResult | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveGroup, setSaveGroup] = useState('')
  const [boardGenPattern, setBoardGenPattern] = useState<BoardPattern>('chessboard')
  const [boardGenCols, setBoardGenCols] = useState('9')
  const [boardGenRows, setBoardGenRows] = useState('6')
  const [boardGenSpacing, setBoardGenSpacing] = useState('20')
  const [boardGenDpi, setBoardGenDpi] = useState('300')

  const shot: Shot | null = shots[current] ?? null
  const detected = shots.filter((s) => s.corners?.length)
  const robot = useRobotWizard(shot?.ref ?? null)
  const mapping = useMappingWizard()
  const stereo = useStereoWizard()
  const stitch = useStitchWizard()

  const boardGeneratorQuery = useMemo(() => {
    const params = new URLSearchParams()
    params.set('pattern', boardGenPattern)
    params.set('cols', String(Number(boardGenCols) || 0))
    params.set('rows', String(Number(boardGenRows) || 0))
    params.set('spacing', String(Number(boardGenSpacing) || 0))
    params.set('dpi', String(Number(boardGenDpi) || 0))
    return params.toString()
  }, [boardGenPattern, boardGenCols, boardGenRows, boardGenSpacing, boardGenDpi])
  const boardGeneratorUrl = withKey(`${BASE_URL}/vision/calibration/board.png?${boardGeneratorQuery}`)
  const boardGeneratorName = `calibration-${boardGenPattern}-${boardGenCols}x${boardGenRows}-${boardGenSpacing}mm-${boardGenDpi}dpi.png`

  async function downloadBoard() {
    setBusy(true)
    try {
      await downloadFile(`/vision/calibration/board.png?${boardGeneratorQuery}`, boardGeneratorName)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function reset() {
    setShots([])
    setCurrent(0)
    setPoints([])
    setResult(null)
    robot.reset()
    mapping.reset()
    stereo.reset()
    stitch.reset()
  }

  function switchMode(next: Mode) {
    setMode(next)
    setResult(null)
    setPoints([])
    robot.reset()
    mapping.reset()
    stereo.reset()
    stitch.reset()
    // 標定板與跨相機模式保留多張影像；單張模式切換時只留目前影像。
    if (next !== 'board' && next !== 'mapping' && next !== 'stereo' && next !== 'stitch' && shots.length > 1) {
      setShots(shot ? [shot] : [])
      setCurrent(0)
    }
  }

  async function detect(target: Shot): Promise<Shot> {
    const body = await api.post<{ found: boolean; corners: number[][]; overlays: Overlay[]; hint?: string }>(
      '/vision/calibration/detect',
      { ref: target.ref, kind: boardKind, cols: Number(cols), rows: Number(rows) },
    )
    return { ...target, corners: body.found ? body.corners : null, overlays: body.overlays ?? [], hint: body.hint ?? '' }
  }

  async function addShot(captured: { ref: string; width: number; height: number; name: string }) {
    let next: Shot = { ...captured, corners: null, overlays: [], hint: '', error: null }
    if (mode === 'board') {
      try {
        next = await detect(next)
      } catch (err) {
        next = { ...next, hint: errorMessage(err) }
      }
    }
    setResult(null)
    if (mode === 'board') {
      setShots((prev) => [...prev, next])
      setCurrent(shots.length)
    } else {
      setShots([next])
      setCurrent(0)
      setPoints([])
    }
  }

  async function capture() {
    if (!sourceId) return
    setBusy(true)
    try {
      const body = await api.post<{ ref: string; width: number; height: number; name: string }>(
        '/vision/calibration/capture', {}, { source_id: Number(sourceId) },
      )
      await addShot(body)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function upload(files: FileList | null) {
    if (!files?.length) return
    setBusy(true)
    try {
      for (const file of Array.from(files).slice(0, 40)) {
        const form = new FormData()
        form.append('image', file)
        const body = await api.postForm<{ ref: string; width: number; height: number; name: string }>('/vision/calibration/capture', form)
        await addShot({ ...body, name: file.name })
        if (mode !== 'board') break
      }
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function redetectAll() {
    setBusy(true)
    try {
      const next = await Promise.all(shots.map((s) => detect(s).catch((err) => ({ ...s, corners: null, hint: errorMessage(err) }))))
      setShots(next)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  async function addPoint(x: number, y: number) {
    let px: [number, number] = [x, y]
    if (snap && shot) {
      try {
        const body = await api.post<{ found: boolean; x: number; y: number }>('/vision/calibration/snap', { ref: shot.ref, x, y })
        if (body.found) px = [body.x, body.y]
      } catch {
        /* 吸附失敗就用點擊位置，不打斷操作 */
      }
    }
    setResult(null)
    if (mode === 'robot') {
      robot.record(px)
      return
    }
    setPoints((prev) => (prev.length >= (mode === 'distance' ? 2 : 200) ? prev : [...prev, { px, world: ['', ''], error: null }]))
  }

  async function solve() {
    if (mode !== 'mapping' && mode !== 'stereo' && !shot) return
    setBusy(true)
    try {
      const base = mode === 'mapping' || mode === 'stereo' ? {} : { image_size: [shot!.width, shot!.height], unit }
      let body: Record<string, unknown>
      if (mode === 'board') {
        body = { ...base, mode: 'board', kind: boardKind, cols: Number(cols), rows: Number(rows), spacing: Number(spacing), views: detected.map((s) => s.corners) }
      } else if (mode === 'mapping') {
        body = mapping.body()
      } else if (mode === 'stereo') {
        body = stereo.body()
      } else if (mode === 'robot') {
        body = { ...base, ...robot.body() }
      } else if (mode === 'points') {
        body = {
          ...base, mode: 'points', world_kind: worldKind,
          points: points.map((p) => ({ px: p.px, world: [Number(p.world[0] || 0), Number(p.world[1] || 0)] })),
        }
      } else {
        body = { ...base, mode: 'distance', distance: Number(distance), points: points.map((p) => ({ px: p.px })) }
      }
      const solved = await api.post<SolveResult>('/vision/calibration/solve', body)
      setResult(solved)
      const world = solved.payload.world as WorldBlock | undefined
      if (mode === 'board') {
        const lens = solved.payload.lens as LensBlock | undefined
        setShots((prev) => {
          const errors = lens?.view_errors ?? []
          let i = 0
          return prev.map((s) => (s.corners?.length ? { ...s, error: errors[i++] ?? null } : s))
        })
      }
      if (mode === 'points' && world?.points) {
        setPoints((prev) => prev.map((p, i) => ({ ...p, error: world.points?.[i]?.error ?? null })))
      }
      if (mode === 'robot') {
        robot.applyResult((solved.payload.robot as RobotBlock | undefined) ?? null)
      }
      if (mode === 'mapping') {
        mapping.applyResult((solved.payload.mapping as MappingBlock | undefined) ?? null)
      }
      if (mode === 'stereo') {
        stereo.applyResult((solved.payload.stereo as StereoBlock | undefined) ?? null)
      }
      toast.success(t('calibration.solved'))
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    if (!result) return
    setBusy(true)
    try {
      await api.post('/vision/calibration/assets', { name: saveName.trim(), group: saveGroup.trim(), payload: result.payload })
      toast.success(t('calibration.saved', { name: saveName.trim() }))
      setSaveOpen(false)
      void calibrations.refetch()
      reset()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const coverage = useMemo(() => {
    if (mode !== 'board' || !shot) return null
    return coverageOf(detected.map((s) => s.corners ?? []), shot.width, shot.height)
  }, [mode, shot, detected])

  const overlays = useMemo<Overlay[]>(() => {
    if (mode === 'board') {
      const base = shot?.overlays ?? []
      if (!coverage || !shot || !showCoverage) return base
      const cellW = shot.width / COVERAGE_COLS
      const cellH = shot.height / COVERAGE_ROWS
      const cells = coverage.missing.map((m) => ({ kind: 'rect', x: m.col * cellW, y: m.row * cellH, w: cellW, h: cellH, color: '#ef4444', width: 1, dash: true } as Overlay))
      const others = detected.filter((s) => s.ref !== shot.ref).flatMap((s) => s.corners ?? [])
      return [...cells, ...(others.length ? [{ kind: 'points', points: others, color: '#38bdf8' } as Overlay] : []), ...base]
    }
    if (mode === 'robot') return robot.overlays
    return points.flatMap((p, i) => {
      const worst = points.reduce((m, q) => Math.max(m, q.error ?? 0), 0)
      const bad = p.error != null && worst > 0 && p.error >= worst
      const label = p.error != null ? `${i + 1}: ${p.error.toFixed(3)} ${unit}` : String(i + 1)
      return [{ kind: 'point', x: p.px[0], y: p.px[1], color: bad ? '#ef4444' : '#22c55e', label } as Overlay]
    })
  }, [mode, shot, points, unit, coverage, detected, showCoverage, robot.overlays])

  const world = worldOf(result)
  const lens = lensOf(result)
  const robotBlock = (result?.payload?.robot as RobotBlock | undefined) ?? null
  const mappingBlock = (result?.payload?.mapping as MappingBlock | undefined) ?? null
  const stereoBlock = (result?.payload?.stereo as StereoBlock | undefined) ?? null
  const canSolve = mode === 'stitch'
    ? false
    : mode === 'board'
    ? detected.length > 0 && Number(spacing) > 0
    : mode === 'mapping'
      ? mapping.canSolve
      : mode === 'stereo'
        ? stereo.canSolve
        : mode === 'robot'
          ? robot.canSolve
          : mode === 'points'
            ? points.length >= (worldKind === 'perspective' ? 4 : worldKind === 'affine' ? 3 : 2) && points.every((p) => p.world[0] !== '' && p.world[1] !== '')
            : points.length === 2 && Number(distance) > 0

  return (
    <Page>
      <PageHeader
        title={t('calibration.title')}
        description={t('calibration.subtitle')}
        actions={
          <Button
            variant="primary"
            icon={<Save size={14} />}
            disabled={!result}
            onClick={() => {
              setSaveName(saveName || t('calibration.defaultName'))
              setSaveOpen(true)
            }}
            data-testid="calib-save"
          >
            {t('calibration.save')}
          </Button>
        }
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-7">
        {(['board', 'points', 'distance', 'robot', 'mapping', 'stereo', 'stitch'] as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => switchMode(m)}
            className={`rounded-lg border p-3 text-left transition ${mode === m ? 'border-brand bg-brand/5' : 'border-line hover:border-brand/40'}`}
            data-testid={`calib-mode-${m}`}
          >
            <div className="flex items-center gap-2 text-sm font-medium">
              {m === 'board' ? <Wand2 size={15} /> : m === 'points' ? <Crosshair size={15} /> : m === 'distance' ? <Ruler size={15} /> : m === 'mapping' ? <ArrowRightLeft size={15} /> : m === 'stereo' ? <Layers3 size={15} /> : m === 'stitch' ? <PanelsTopLeft size={15} /> : <Move size={15} />}
              {t(`calibration.modes.${m}.title`)}
            </div>
            <p className="mt-1 text-xs text-subtle">{t(`calibration.modes.${m}.hint`)}</p>
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        {mode === 'mapping' ? (
          <MappingWizard
            wizard={mapping}
            onChange={() => setResult(null)}
            onError={(message) => toast.error(message)}
          />
        ) : mode === 'stereo' ? (
          <StereoWizard
            wizard={stereo}
            onChange={() => setResult(null)}
            onError={(message) => toast.error(message)}
            onSolved={(solved) => {
              setResult(solved)
              stereo.applyResult((solved.payload.stereo as StereoBlock | undefined) ?? null)
              toast.success(t('calibration.solved'))
            }}
          />
        ) : mode === 'stitch' ? (
          <StitchWizard
            wizard={stitch}
            onError={(message) => toast.error(message)}
            onSaved={(message) => toast.success(message)}
          />
        ) : (
        <Card>
          <CardHeader
            title={t('calibration.picture')}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  value={sourceId}
                  onChange={(e) => setSourceId(e.target.value)}
                  placeholder={t('calibration.pickSource')}
                  aria-label={t('calibration.pickSource')}
                  options={(sources.data?.items ?? []).map((s) => ({ value: String(s.id), label: s.name }))}
                  data-testid="calib-source"
                />
                <Button icon={<Camera size={14} />} disabled={!sourceId} loading={busy} onClick={() => void capture()} data-testid="calib-capture">
                  {t('calibration.capture')}
                </Button>
                <Button icon={<Upload size={14} />} loading={busy} onClick={() => fileInput.current?.click()} data-testid="calib-upload">
                  {t('calibration.upload')}
                </Button>
                <input ref={fileInput} type="file" accept="image/*" multiple={mode === 'board'} className="hidden" onChange={(e) => { void upload(e.target.files); e.target.value = '' }} />
              </div>
            }
          />
          <CardBody>
            {shot ? (
              <>
                <ImageViewer
                  src={imageUrl(shot.ref, 1600)}
                  imageWidth={shot.width}
                  imageHeight={shot.height}
                  overlays={overlays}
                  onPick={mode === 'board' ? undefined : (x, y) => void addPoint(x, y)}
                  className="h-[420px]"
                  stateKey="calibration:main"
                />
                <p className="mt-2 text-xs text-subtle">
                  {mode === 'board' ? (shot.corners?.length ? t('calibration.boardFound', { count: shot.corners.length }) : shot.hint || t('calibration.boardMissing')) : t('calibration.clickHint')}
                </p>
              </>
            ) : (
              <EmptyState title={t('calibration.noPicture')} description={t('calibration.noPictureHint')} icon={<Camera size={22} />} />
            )}
          </CardBody>
        </Card>
        )}

        <div className="space-y-4">
          {mode === 'mapping' || mode === 'stereo' || mode === 'stitch' ? null : mode === 'board' ? (
            <Card>
              <CardHeader title={t('calibration.board')} />
              <CardBody className="space-y-3">
                <Select
                  label={t('calibration.boardKind')}
                  value={boardKind}
                  onChange={(e) => setBoardKind(e.target.value as BoardKind)}
                  options={(['chessboard', 'circles', 'acircles'] as BoardKind[]).map((k) => ({ value: k, label: t(`calibration.boardKinds.${k}`) }))}
                  data-testid="calib-board-kind"
                />
                <div className="grid grid-cols-3 gap-2">
                  <TextInput label={t('calibration.cols')} value={cols} inputMode="numeric" onChange={(e) => setCols(e.target.value)} data-testid="calib-cols" />
                  <TextInput label={t('calibration.rows')} value={rows} inputMode="numeric" onChange={(e) => setRows(e.target.value)} data-testid="calib-rows" />
                  <TextInput label={t('calibration.spacing')} value={spacing} inputMode="decimal" suffix={unit} onChange={(e) => setSpacing(e.target.value)} data-testid="calib-spacing" />
                </div>
                <p className="text-xs text-subtle">{t('calibration.boardHint')}</p>
                {coverage ? (
                  <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="calib-coverage">
                    <Badge tone={coverage.covered === coverage.cells ? 'ok' : coverage.edgeMissing ? 'warning' : 'neutral'}>{t('calibration.coverage', { covered: coverage.covered, cells: coverage.cells })}</Badge>
                    <span className="text-subtle">{coverage.covered === coverage.cells ? t('calibration.coverageOk') : coverage.edgeMissing ? t('calibration.coverageEdge', { n: coverage.edgeMissing }) : t('calibration.coverageMore')}</span>
                    <label className="ml-auto flex items-center gap-1 text-subtle">
                      <input type="checkbox" checked={showCoverage} onChange={(e) => setShowCoverage(e.target.checked)} />
                      {t('calibration.showCoverage')}
                    </label>
                  </div>
                ) : null}
                <Button loading={busy} disabled={!shots.length} onClick={() => void redetectAll()} data-testid="calib-redetect">
                  {t('calibration.redetect')}
                </Button>
                <Table>
                  <THead>
                    <Th>{t('calibration.shot')}</Th>
                      <Th>{t('calibration.found')}</Th>
                      <Th align="right">{t('calibration.viewError')}</Th>
                      <Th /></THead>
                  <TBody>
                    {shots.length ? shots.map((s, i) => (
                      <Tr key={s.ref} selected={i === current} onClick={() => setCurrent(i)} testId={`calib-shot-${i}`}>
                        <Td>{localiseDataName(s.name, i18next.language as Language)}</Td>
                        <Td>{s.corners?.length ? <Badge tone="ok">{s.corners.length}</Badge> : <Badge tone="critical">{t('calibration.notFound')}</Badge>}</Td>
                        <Td align="right">{s.error == null ? '—' : `${s.error.toFixed(3)} px`}</Td>
                        <Td align="right">
                          <IconButton
                            label={t('common.delete')}
                            onClick={() => {
                              setShots((prev) => prev.filter((_, j) => j !== i))
                              setCurrent(0)
                              setResult(null)
                            }}
                          >
                            <Trash2 size={13} />
                          </IconButton>
                        </Td>
                      </Tr>
                    )) : <EmptyRow colSpan={4} message={t('calibration.noShots')} />}
                  </TBody>
                </Table>
              </CardBody>
            </Card>
          ) : null}

          {mode === 'mapping' || mode === 'stereo' || mode === 'stitch' ? null : mode === 'board' ? (
            <Card>
              <CardHeader title={t('calibration.boardGenerator.title')} />
              <CardBody className="space-y-3">
                <Select
                  label={t('calibration.boardGenerator.pattern')}
                  value={boardGenPattern}
                  onChange={(e) => setBoardGenPattern(e.target.value as BoardPattern)}
                  options={(['chessboard', 'acircles'] as BoardPattern[]).map((k) => ({ value: k, label: t(`calibration.boardGenerator.patterns.${k}`) }))}
                  data-testid="calib-boardgen-pattern"
                />
                <div className="grid grid-cols-2 gap-2">
                  <TextInput label={t('calibration.cols')} value={boardGenCols} inputMode="numeric" onChange={(e) => setBoardGenCols(e.target.value)} data-testid="calib-boardgen-cols" />
                  <TextInput label={t('calibration.rows')} value={boardGenRows} inputMode="numeric" onChange={(e) => setBoardGenRows(e.target.value)} data-testid="calib-boardgen-rows" />
                  <TextInput label={t('calibration.spacing')} value={boardGenSpacing} inputMode="decimal" suffix="mm" onChange={(e) => setBoardGenSpacing(e.target.value)} data-testid="calib-boardgen-spacing" />
                  <TextInput label={t('calibration.boardGenerator.dpi')} value={boardGenDpi} inputMode="numeric" onChange={(e) => setBoardGenDpi(e.target.value)} data-testid="calib-boardgen-dpi" />
                </div>
                <div className="overflow-hidden rounded-md border border-line bg-white">
                  <img src={boardGeneratorUrl} alt={t('calibration.boardGenerator.preview')} className="max-h-64 w-full object-contain" />
                </div>
                <p className="text-xs text-subtle">{t('calibration.boardGenerator.printHint')}</p>
                <Button icon={<Download size={14} />} loading={busy} onClick={() => void downloadBoard()} data-testid="calib-boardgen-download">
                  {t('calibration.boardGenerator.download')}
                </Button>
              </CardBody>
            </Card>
          ) : mode === 'robot' ? (
            <RobotWizard
              wizard={robot}
              unit={unit}
              snap={snap}
              onSnap={setSnap}
              hasPicture={!!shot}
              onChange={() => setResult(null)}
              onLocateError={(message) => toast.error(message)}
            />
          ) : (
            <Card>
              <CardHeader title={mode === 'points' ? t('calibration.robotPoints') : t('calibration.twoPoints')} />
              <CardBody className="space-y-3">
                <Checkbox label={t('calibration.snap')} hint={t('calibration.snapHint')} checked={snap} onChange={setSnap} />
                {mode === 'points' ? (
                  <Select
                    label={t('calibration.worldKind')}
                    value={worldKind}
                    onChange={(e) => setWorldKind(e.target.value as WorldKind)}
                    options={(['affine', 'perspective', 'scale'] as WorldKind[]).map((k) => ({ value: k, label: t(`calibration.worldKinds.${k}`) }))}
                    hint={t(`calibration.worldKindHints.${worldKind}`)}
                    data-testid="calib-world-kind"
                  />
                ) : (
                  <TextInput
                    label={t('calibration.realDistance')}
                    value={distance}
                    inputMode="decimal"
                    suffix={unit}
                    onChange={(e) => setDistance(e.target.value)}
                    hint={t('calibration.realDistanceHint')}
                    data-testid="calib-distance"
                  />
                )}
                <Table>
                  <THead>
                    <Th>#</Th>
                      <Th>{t('calibration.pixel')}</Th>
                      {mode === 'points' ? <Th>{`X (${unit})`}</Th> : null}
                      {mode === 'points' ? <Th>{`Y (${unit})`}</Th> : null}
                      <Th align="right">{t('calibration.pointError')}</Th>
                      <Th /></THead>
                  <TBody>
                    {points.length ? points.map((p, i) => (
                      <Tr key={`${p.px[0]}-${p.px[1]}-${i}`} testId={`calib-point-${i}`}>
                        <Td>{i + 1}</Td>
                        <Td>{`${p.px[0].toFixed(1)}, ${p.px[1].toFixed(1)}`}</Td>
                        {mode === 'points' ? (
                          <>
                            <Td>
                              <TextInput
                                value={p.world[0]}
                                inputMode="decimal"
                                onChange={(e) => setPoints((prev) => prev.map((q, j) => (j === i ? { ...q, world: [e.target.value, q.world[1]] } : q)))}
                                data-testid={`calib-world-x-${i}`}
                              />
                            </Td>
                            <Td>
                              <TextInput
                                value={p.world[1]}
                                inputMode="decimal"
                                onChange={(e) => setPoints((prev) => prev.map((q, j) => (j === i ? { ...q, world: [q.world[0], e.target.value] } : q)))}
                                data-testid={`calib-world-y-${i}`}
                              />
                            </Td>
                          </>
                        ) : null}
                        <Td align="right">{p.error == null ? '—' : `${p.error.toFixed(3)}`}</Td>
                        <Td align="right">
                          <IconButton label={t('common.delete')} onClick={() => { setPoints((prev) => prev.filter((_, j) => j !== i)); setResult(null) }}>
                            <Trash2 size={13} />
                          </IconButton>
                        </Td>
                      </Tr>
                    )) : <EmptyRow colSpan={mode === 'points' ? 6 : 4} message={t('calibration.noPoints')} />}
                  </TBody>
                </Table>
              </CardBody>
            </Card>
          )}

          {mode === 'stitch' ? null : <Card>
            <CardHeader title={t('calibration.result')} />
            <CardBody className="space-y-2">
              <Select
                label={t('calibration.unit')}
                value={unit}
                onChange={(e) => { setUnit(e.target.value); setResult(null) }}
                options={UNITS.map((u) => ({ value: u.value, label: t(`calibration.units.${u.key}`) }))}
                hint={t('calibration.unitHint')}
                data-testid="calib-unit"
              />
              <Button variant="primary" loading={busy} disabled={!canSolve} onClick={() => void solve()} data-testid="calib-solve">
                {t('calibration.calculate')}
              </Button>
              {result ? (
                <div className="space-y-2 text-sm" data-testid="calib-result">
                  {robotBlock ? <RobotResult robot={robotBlock} unit={unit} /> : null}
                  {mappingBlock ? <MappingResult mapping={mappingBlock} /> : null}
                  {stereoBlock ? <StereoResult stereo={stereoBlock} /> : null}
                  {world ? (
                    <>
                      <div className="flex items-baseline gap-2">
                        <span className="text-xl font-semibold tabular-nums">{world.mm_per_px.toFixed(5)}</span>
                        <span className="text-xs text-subtle">{`${unit}/px`}</span>
                        {result.quality.world ? <Badge tone={QUALITY_TONE[result.quality.world]}>{t(`calibration.quality.${result.quality.world}`)}</Badge> : null}
                      </div>
                      {world.points?.length ? (
                        <p className="text-xs text-subtle">{t('calibration.fitError', { rms: world.rms.toFixed(3), max: world.max_error.toFixed(3), unit })}</p>
                      ) : null}
                    </>
                  ) : null}
                  {lens ? (
                    <p className="text-xs text-subtle">
                      {t('calibration.lensError', { views: lens.views, rms: lens.rms.toFixed(3) })}{' '}
                      {result.quality.lens ? <Badge tone={QUALITY_TONE[result.quality.lens]}>{t(`calibration.quality.${result.quality.lens}`)}</Badge> : null}
                    </p>
                  ) : null}
                  {lens && lens.rms > RMS_WARN_PX ? (
                    <p className="text-xs text-warning" data-testid="calib-rms-warning">{t('calibration.rmsWarning', { rms: lens.rms.toFixed(2) })}</p>
                  ) : null}
                  {result.warnings?.length ? (
                    <ul className="list-disc space-y-0.5 pl-4 text-xs text-warning" data-testid="calib-warnings">
                      {result.warnings.map((w) => <li key={w}>{w}</li>)}
                    </ul>
                  ) : null}
                  <p className="text-xs text-subtle">{t('calibration.useHint')}</p>
                </div>
              ) : (
                <p className="text-xs text-subtle">{t(`calibration.modes.${mode}.steps`)}</p>
              )}
            </CardBody>
          </Card>}

          <Card>
            <CardHeader title={t('calibration.existing')} />
            <CardBody>
              {calibrations.data?.items.length ? (
                <ul className="space-y-1 text-xs">
                  {calibrations.data.items.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{localiseDataName(a.name, i18next.language as Language)}</span>
                      <span className="shrink-0 text-subtle">{String((a.meta as { summary?: string } | undefined)?.summary ?? '')}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-subtle">{t('calibration.noneYet')}</p>
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <Modal open={saveOpen} onClose={() => setSaveOpen(false)} title={t('calibration.save')}>
        <div className="space-y-3">
          <TextInput label={t('common.name')} value={saveName} onChange={(e) => setSaveName(e.target.value)} data-testid="calib-save-name" />
          <TextInput label={t('common.group')} value={saveGroup} onChange={(e) => setSaveGroup(e.target.value)} />
          <p className="text-xs text-subtle">{result?.summary}</p>
          <div className="flex justify-end gap-2">
            <Button onClick={() => setSaveOpen(false)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={busy} disabled={!saveName.trim()} onClick={() => void save()} data-testid="calib-save-confirm">
              {t('common.save')}
            </Button>
          </div>
        </div>
      </Modal>
    </Page>
  )
}

export default CalibrationPage
