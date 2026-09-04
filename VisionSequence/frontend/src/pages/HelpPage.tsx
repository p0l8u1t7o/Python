/**
 * 說明頁（HelpPage）`/help`：快速上手、名詞定義（docs/glossary.html 的表）、埠型別與顏色圖例、
 * 工具目錄（從 /tool-types 動態列出）、快捷鍵、自動化接口摘要、帳號與鎖定。
 * 名詞表是文件內容，直接以英文呈現（與 docs/glossary.html 同一份）；分頁標題與欄位名走 i18n。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { Plug } from 'lucide-react'

import { iconFor } from '@/components/editor/ToolNode'
import { Page } from '@/components/layout/AppShell'
import { Button, Card, CardBody, CardHeader, LoadingState, PageHeader, Tabs } from '@/components/ui'
import { PORT_HEX } from '@/lib/ports'
import { useToolTypes } from '@/lib/queries'
import type { PortType } from '@/lib/types'

type HelpTab = 'quickstart' | 'glossary' | 'ports' | 'tools' | 'shortcuts' | 'automation' | 'accounts'
const TABS: HelpTab[] = ['quickstart', 'glossary', 'ports', 'tools', 'shortcuts', 'automation', 'accounts']

const QUICKSTART: { title: string; body: string }[] = [
  { title: 'Create a flow', body: 'Press "New flow" on the Flows page, or copy one of the demo flows. A flow belongs to the line rather than to a person: any engineer can see and edit it, and the Owner column only records who created it.' },
  { title: 'Acquire an image', body: 'Insert an "Image source" step from the palette and pick a camera, folder or synthetic source from the source library — or use "Upload scratch image" in the toolbar to provide one image for previews only (it does not join the library). When the camera is on another PC, or needs a vendor SDK such as Basler or IDS, install the capture client on that PC ("Download capture client" on the Image sources page), connect it to the server, and add a "capture client camera" source naming the client and the channel.' },
  { title: 'Add tools', body: 'Drag a tool from the palette onto the canvas (or click to insert it at the right), then drag from one step\'s output port to the next step\'s input port. Only ports of the same colour connect.' },
  { title: 'Draw an ROI', body: 'For a tool with a region parameter, press "Edit on image" on the tool page or in the inspector and drag out a rectangle, circle, polygon or any other shape directly on the image. Coordinates are pixels in that step\'s input image.' },
  { title: 'Preview', body: '"Preview" in the toolbar runs the current canvas, unsaved changes included, and keeps every intermediate image; "Re-run with last image" pins the same image while you tune. The icon beside a step name opens its tool page, where changing a parameter re-runs to that step and shows the before and after images with a histogram.' },
  { title: 'Judge', body: 'Use the "Judge" tool to give an OK or NG, and "Named output" to name the values you want returned to the automation system.' },
  { title: 'Save', body: 'Ctrl+S, or "Save" in the toolbar. "Run once" and "Continuous" use the saved version.' },
  { title: 'Trigger it from outside', body: 'An external system triggers a flow with HTTP POST /api/vision/flows/{id}/run (optionally with an image) or a TCP command, and collects the result from the response or over SSE. Details on the Automation API tab.' },
  { title: 'Template gallery', body: '"Create from template" on the Flows page, or "Load template" in the editor toolbar: 18 built-in templates covering counting, measurement, defects, colour, code reading and deep learning (stock YOLO models and taught models). Pick the matching "Example: …" image source and it runs as it is. Your own flow can be saved as a template too.' },
  { title: 'AI assistant', body: 'The AI assistant page: upload an image, mark the areas to inspect (ROI01, ROI02… each with its own hint) and describe what you want in a sentence. The assistant checks it has enough to go on, generates the flow and runs it on that image. Mark each thumbnail with the verdict it should get and the assistant ranks its candidates against them and auto-tunes. Refine it in words, then "Save as flow". History restores a past session and AI skills takes your own notes; with the working mode set to agentic, the assistant tries, edits and verifies step by step with a timeline. The global assistant in the bottom-right corner opens on any page: it answers questions from the documentation with links, edits the current flow in the editor, and consults or tunes from the data on the batch page.' },
  { title: 'Batch testing and the Golden Set', body: '"Batch test" in the sidebar: pick a flow, upload images or grab them from a source to build an image set, and every run keeps its per-image results. Label the images with their expected OK or NG to get a hit rate, insights and suggested thresholds; change parameters, run the same set again and compare; then write it back to the flow or save it as a recipe. You can also ask the AI assistant to consult on or tune from the data. Tick cases and save them to a Golden Set as a regression baseline.' },
  { title: 'Deep-learning teaching', body: '"Deep learning" in the sidebar: create a teaching project, collect samples (uploaded or grabbed from a source), label classes or shapes (smart select included), train, and export the model to the asset library for a DL tool to use in a flow.' },
  { title: 'Source and asset groups', body: 'Both the image source library and the asset library support groups: filter with the chips above the list, and rename or delete under "Manage groups". The example sources and assets are all in the "Examples" group.' },
]

const GLOSSARY_PAGES: [string, string, string, string][] = [
  ['Dashboard', '/', 'DashboardPage', 'The flow list, and the live image and inspection detail of the selected flow'],
  ['Flows', '/flows', 'FlowsPage', 'The flow list'],
  ['Flow editor', '/flows/:id', 'FlowEditorPage', 'Canvas, image viewer and inspector'],
  ['Tool page', '/flows/:id/tools/:nodeId', 'ToolPage', 'A page dedicated to tuning one step'],
  ['Image sources', '/sources', 'SourcesPage', 'Cameras, folders and synthetic sources'],
  ['Assets', '/assets', 'AssetsPage', 'Template images and model files'],
  ['Users', '/users', 'UsersPage', 'Account management (administrators)'],
  ['Settings', '/settings', 'SettingsPage', 'Keys, theme, language, the account and the password'],
  ['Help', '/help', 'HelpPage', 'Definitions and how-to'],
  ['Statistics', '/flows/:id/stats', 'StatsPage', 'Run history, the yield trend, hourly OK/NG'],
  ['Teach page', '/flows/:id/teach', 'TeachPage', 'Every teaching parameter grouped by step with a live preview, the recipe dropdown, and "mark as commissioned"'],
  ['Golden Set', '/flows/:id/golden', 'GoldenPage', 'Image cases with expectations, and regression testing (regressed cases first)'],
  ['Batch test', '/batch', 'BatchPage', 'Run an image set through a flow; every run is stored, with expected labels, insights, tuning, comparison and AI consultation'],
  ['Integration', '/integration', 'IntegrationLayout', 'HTTP testing with the result format, TCP commands with their failure codes, event monitoring, Modbus and TCP connections, and the capture client'],
  ['Audit log', '/audit', 'AuditPage', 'Who changed what and when (administrators)'],
  ['Sign in', '/login', 'LoginPage', 'Sign in, or create the first administrator'],
  ['Deep learning', '/dl', 'DlPage', 'Teaching projects: samples, labelling, datasets, training and model export'],
  ['AI assistant', '/agent', 'AgentPage', 'Image plus ROIs plus a sentence, into a generated flow; provider settings and AI skills'],
]

const GLOSSARY_EDITOR: [string, string, string][] = [
  ['Toolbar', 'EditorToolbar', 'Two rows: the flow name, save, templates, recipes and the binding; preview, re-run with the last image, upload a scratch image, continuous, reset and help'],
  ['Tool palette', 'ToolPalette', 'Top of the left column: the tools you can insert, grouped by category and searchable; drag onto the canvas to add'],
  ['Step list', 'NodeList', 'Bottom of the left column: every step in the flow; clicking focuses the canvas on it'],
  ['Image viewer', 'ImageViewer', 'Top of the middle column: the image, the overlays and ROI editing'],
  ['Canvas', 'FlowCanvas', 'Bottom of the middle column: the React Flow canvas'],
  ['Inspector', 'Inspector', 'Right column: the flow\'s shared settings, or the selected step\'s basics and "Open tool page"'],
  ['Results panel', 'ResultsPanel', 'The Results tab in the inspector: recent runs, output values, errors and warnings'],
  ['Recipe manager', 'RecipeManager', '"Manage recipes" on the teach page: add, rename, set as bound, delete, and the override table'],
  ['Lock banner', 'LockBanner', 'The yellow banner shown while the engine is locked'],
]

const GLOSSARY_CORE: [string, string, string][] = [
  ['Flow', 'Flow', 'One inspection graph of steps and edges. It belongs to the line: any engineer can edit it'],
  ['Role', 'admin / engineer / operator', 'An administrator manages accounts, connections and settings; an engineer edits flows; an operator may only change teaching parameters and change over'],
  ['Teaching parameter / teach page', 'Param.teach / TeachPage', 'A parameter a tool marks as needing adjustment on the line; the teach page lists only these'],
  ['Commissioned', 'Flow.commissioned', 'Set by "Mark as commissioned" on the teach page; until then every run carries a warning without being blocked'],
  ['Recipe', 'FlowRecipe', 'A set of parameter overrides for one flow, for changeovers. Run, preview and TCP recipe= can name one; without one the bound recipe applies'],
  ['Golden case', 'GoldenCase', 'An image with an expectation (OK, NG or any), from an upload or a batch result'],
  ['Regression / baseline', 'Regression / Baseline', 'Run every case against its expectation and the baseline; regressed means the baseline matched and this run does not'],
  ['Station', 'station_id', 'The station identifier carried by every run (VISION_STATION_ID)'],
  ['Connection', 'Connection', 'An outgoing connection to Modbus TCP or a host system (modbus_tcp, modbus_server, tcp_client, dio_sim, plugin); write_modbus refers to it by name'],
  ['Export / import', '.flow.json', 'A stably serialised flow file; import upserts on the name and the {SOURCE} placeholder is replaced by the source you choose'],
  ['Node / step', 'Node', 'One box on the canvas — an instance of a tool'],
  ['Tool', 'ToolTypeDef', 'A kind in the palette (grayscale, blob…); the key is its unique identifier'],
  ['Edge', 'Edge', 'A line between steps: an output port to an input port'],
  ['Port', 'Port', 'Inputs on the left of a step, outputs on the right; each has a type'],
  ['Flow handle', 'flow port', 'An output port of type flow (true, false and so on); it connects only to a step\'s diamond control input'],
  ['Parameter', 'Param', 'A step\'s setting; the kinds are a closed set (number, select, roi…)'],
  ['Region / ROI', 'Region', 'The area drawn on the image to inspect (rectangle, rotated rectangle, circle, annulus, polygon, line)'],
  ['Overlay', 'Overlay', 'The result graphics a tool draws on the image (boxes, circles, points, text)'],
  ['Run', 'Run', 'One execution of the flow, complete or up to a step; the result is OK, NG or failed'],
  ['Preview', 'Preview', 'Runs the unsaved graph and keeps every intermediate image; nothing is written to history'],
  ['Run once', 'Run once', 'Runs the saved graph once; written to history and the statistics'],
  ['Continuous', 'Continuous', 'Runs repeatedly at the configured interval'],
  ['Scratch image', 'Scratch image', 'An image uploaded only for a preview; it does not join the source library'],
  ['Image source', 'Image source', 'The definition of a camera, folder, synthetic generator, pushed image or capture client camera'],
  ['Capture client', 'vscapture', 'The desktop program on the camera\'s PC: it drives webcams, Basler and IDS cameras and connects out to the server\'s capture port 9100. Shared memory on one machine, lossless TCP across machines'],
  ['Capture source', 'kind=capture', 'An image source naming a client and a channel: on demand (a fresh frame for every run) or continuous stream (the latest frame)'],
  ['Asset', 'Asset', 'A file: a template image, an ONNX model, a dataset archive'],
  ['Judge', 'Judge', 'The OK/NG conclusion, from the judge tool'],
  ['Named output', 'Output', 'A key and value returned to the automation system, from the output tool'],
  ['Engine lock', 'EngineLock', 'An integrator holding the hardware: everyone else can edit but not execute'],
  ['Integrator', 'Integrator', 'An automation system calling with an API key'],
  ['Image archive', 'archive', 'Optionally writing run images to disk, off by default and enabled per flow, so a defect from last week can still be looked at'],
  ['Reset', 'Reset', 'Clears that flow\'s in-memory run records and statistics'],
  ['Template library', 'FlowTemplate', 'Flow templates, built in or your own; create a flow from one, load one onto the canvas, or save the canvas as one'],
  ['Batch test', 'Batch test', 'Run a set of images through the current graph and see the yield and every verdict'],
  ['Favourites', 'Favorites', 'Tools starred in the palette (stored in the browser)'],
]

const GLOSSARY_STATUS: [string, string, string][] = [
  ['OK', 'green', 'Judged good'],
  ['NG', 'red', 'Judged a reject'],
  ['Failed', 'dark red border', 'A tool error, a timeout or no image; the step shows the message on the canvas'],
  ['Skipped', 'faded grey', 'A branch not taken, or an upstream failure'],
  ['Running', 'pulsing border', 'In progress'],
]

const PORT_ROWS: [PortType, string, string][] = [
  ['image', 'blue', 'Images'],
  ['region', 'purple', 'ROIs'],
  ['number', 'green', 'Numbers'],
  ['bool', 'orange', 'Booleans'],
  ['string', 'yellow', 'Strings'],
  ['points', 'cyan', 'Point sets'],
  ['contours', 'indigo', 'Contours'],
  ['matches', 'pink', 'Match and detection results'],
  ['list', 'teal', 'General lists, overlays included'],
  ['any', 'grey-white', 'Anything'],
  ['flow', 'grey (diamond)', 'Branching'],
]

const SHORTCUTS: [string, string][] = [
  ['Ctrl+S', 'Save the flow'],
  ['Right-click a step', 'Step menu: open the tool page, duplicate, disable, delete, copy or paste parameters'],
  ['Ctrl+Z', 'Undo'],
  ['Ctrl+C / Ctrl+V', 'Copy and paste the selected steps, internal edges included'],
  ['Delete / Backspace', 'Delete the selected steps or edges'],
  ['Esc', 'Clear the selection, or leave ROI editing'],
  ['Left-drag (select mode)', 'Rubber-band several steps; middle- or right-drag pans the canvas'],
  ['Shift+drag (pan mode)', 'Rubber-band selection'],
  ['Scroll wheel', 'Zoom the image viewer and the canvas'],
  ['F / 1 / + / − (image viewer)', 'Fit, 1:1, zoom in, zoom out'],
  ['Double-click the image', 'Fit to window'],
]

const AUTOMATION = [
  { title: 'HTTP trigger', code: 'POST /api/vision/flows/{id}/run?wait=1\nHeaders: X-API-Key: <key>  (or Authorization: Bearer <token>)\nmultipart: image=<file>   or   JSON: {"context": {...}}\n-> 200 RunReport (wait=1) / 202 {"queued": true} (wait=0)' },
  { title: 'Preview (what the tool page uses)', code: 'POST /api/vision/flows/{id}/preview\n{"graph": {...}, "reuse_image_ref": "...", "until_node": "blob", "analysis": true}' },
  { title: 'Scratch image / reset', code: 'POST /api/vision/flows/{id}/scratch-image  (multipart image) -> {ref,width,height,name}\nDELETE /api/vision/flows/{id}/recent -> clears the in-memory run records and statistics (SSE sends cleared)' },
  { title: 'Event stream (SSE)', code: 'GET /api/vision/flows/{id}/stream?since=<seq>\nEvents: run_started / run_finished (with run) / stats / continuous / lock / cleared / ping (a 15 second heartbeat)' },
  { title: 'Capture client (the camera is on another PC)', code: 'Image sources -> "Download capture client" -> unzip and run VisionSequenceCapture.exe on the camera\'s PC\nConnection: the server address and port 9100 (VISION_CAPTURE_PORT), a client name, and the key when the server sets VISION_CAPTURE_AUTH or API_KEY\nChannel: choose the camera, open it, start acquiring; draw an ROI to send only that region\nWeb: add an image source of kind=capture {client, channel, mode: on_demand|stream, timeout_ms, fresh, encoding}\nHeadless: VisionSequenceCapture-console.exe --headless --connect  (for Task Scheduler or a service wrapper)' },
  { title: 'TCP', code: 'One command per line (terminated with \\n, case-insensitive), one JSON reply per line:\nRUN <flow id or name> [key=value ...] -> {"ok": true, "status": "ok|ng|failed", "judge": "OK", "outputs": {...}, "duration_ms": 12.3, "run_id": "..."}\nTRIGGER <flow>   -> trigger without waiting, {"ok": true, "queued": true}\nSTATUS [flow]    -> statistics; without a flow, the capacity and the engine lock\nSTART <flow> / STOP <flow> -> continuous mode\nLOCK [reason=\"...\" ttl=600] / UNLOCK -> hold the hardware: the interface can edit but not run\nLIST / PING\nImages are pushed into an image source of kind=upload with POST /api/vision/sources/{id}/push.' },
]

const ACCOUNTS = [
  'The first time you use it there are no accounts at all, and the sign-in page lets you create the first administrator.',
  'Administrator: manages accounts, role permissions and system settings. Engineer (the default): creates and edits flows, sources, assets, deep-learning teaching, batch tests and Golden Sets. Operator: runs inspections, starts and stops continuous mode, changes over between recipes, and adjusts on-site parameters on the teach page.',
  'Role permissions: that split is the factory setting, not a fixed rule. On the Users page an administrator ticks function by function what an engineer and an operator may use — deep learning, batch testing, the audit trail, the outgoing connections. Administrators always have everything, and the server checks every request, so an untick cannot be worked around by typing the address.',
  'A flow belongs to the line, not to a person: every engineer can see and edit every flow, and the Owner column only records who created it.',
  'An integrator (an automation system) calls with an API key (X-API-Key) and can always execute a flow.',
  'Engine lock: an integrator takes it over HTTP (POST /api/vision/lock) or TCP (LOCK), which stops every continuous run and leaves everyone else able to edit but not preview or run. A banner across the top of the interface says who holds it and why; an administrator or the holder can release it from there, and a lock can carry a timeout after which it releases itself.',
  'Change your own display name and password on the Settings page; an administrator can reset someone else\'s password, change roles and disable an account on the Users page.',
]

function Table({ head, rows }: { head: string[]; rows: (string | React.ReactNode)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>{head.map((h) => <th key={h} className="table-header">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row, i) => (
            <tr key={i}>{row.map((cell, j) => <td key={j} className={`table-cell ${j === 1 ? 'font-mono text-xs' : ''}`}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ToolsCatalogue() {
  const { t } = useTranslation()
  const catalogue = useToolTypes()
  const groups = useMemo(() => {
    const map = new Map<string, { label: string; items: NonNullable<typeof catalogue.data>['items'] }>()
    for (const def of catalogue.data?.items ?? []) {
      const g = map.get(def.category) ?? { label: def.category_label, items: [] }
      g.items.push(def)
      map.set(def.category, g)
    }
    return [...map.values()]
  }, [catalogue.data])
  if (catalogue.isPending) return <LoadingState compact />
  return (
    <div className="space-y-4" data-testid="help-tools">
      {groups.map((group) => (
        <Card key={group.label}>
          <CardHeader title={group.label} description={t('help.toolsCount', { count: group.items.length })} />
          <CardBody className="divide-y divide-line !p-0">
            {group.items.map((def) => {
              const Icon = iconFor(def.icon)
              return (
                <div key={def.key} className="px-4 py-3">
                  <p className="flex items-center gap-2 text-sm font-semibold">
                    <Icon size={15} className="text-brand" /> {def.label}
                    <span className="font-mono text-[11px] font-normal text-muted">{def.key}</span>
                    {def.heavy ? <span className="text-[11px] font-normal text-warning">{t('editor.heavy')}</span> : null}
                  </p>
                  {def.description ? <p className="mt-0.5 text-xs text-muted">{def.description}</p> : null}
                  <div className="mt-1.5 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
                    <p>
                      <span className="font-medium text-muted">{t('editor.inputs')}: </span>
                      {def.inputs.length ? def.inputs.map((p, i) => (
                        <span key={`${p.key}-${i}`} className="mr-2 inline-flex items-center gap-1">
                          <span className="inline-block size-2 rounded-full" style={{ background: PORT_HEX[p.type] }} />{p.label}<span className="text-subtle">({p.type}{p.required ? '' : '?'})</span>
                        </span>
                      )) : '—'}
                    </p>
                    <p>
                      <span className="font-medium text-muted">{t('editor.outputs')}: </span>
                      {def.outputs.filter((p) => !p.implicit).map((p, i) => (
                        <span key={`${p.key}-${i}`} className="mr-2 inline-flex items-center gap-1">
                          <span className={`inline-block size-2 ${p.type === 'flow' ? 'rotate-45' : 'rounded-full'}`} style={{ background: PORT_HEX[p.type] }} />{p.label}<span className="text-subtle">({p.type})</span>
                        </span>
                      ))}
                    </p>
                  </div>
                  {def.params.length ? (
                    <p className="mt-1 text-xs">
                      <span className="font-medium text-muted">{t('editor.parameters')}: </span>
                      {def.params.map((p) => `${p.label} (${p.kind}${p.unit ? `, ${p.unit}` : ''})`).join(', ')}
                    </p>
                  ) : null}
                </div>
              )
            })}
          </CardBody>
        </Card>
      ))}
    </div>
  )
}

export function HelpPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const initial = params.get('tab') as HelpTab | null
  const [tab, setTab] = useState<HelpTab>(initial && TABS.includes(initial) ? initial : 'quickstart')
  const change = (next: HelpTab) => {
    setTab(next)
    setParams({ tab: next }, { replace: true })
  }
  return (
    <Page>
      <PageHeader title={t('help.title')} description={t('help.subtitle')} />
      <Tabs value={tab} onChange={change} tabs={TABS.map((value) => ({ value, label: t(`help.tabs.${value}`) }))} className="mb-4 flex-wrap" />
      <div data-testid={`help-${tab}`}>
        {tab === 'quickstart' ? (
          <ol className="space-y-3">
            {QUICKSTART.map((step, i) => (
              <li key={step.title} className="card flex gap-3 p-4">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-sm font-bold text-brand">{i + 1}</span>
                <div>
                  <p className="text-sm font-semibold">{step.title}</p>
                  <p className="mt-0.5 text-sm leading-relaxed text-muted">{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}
        {tab === 'glossary' ? (
          <div className="space-y-4">
            <Card><CardHeader title={t('help.glossary.pages')} /><CardBody className="!p-0"><Table head={[t('help.cols.zh'), t('help.cols.route'), t('help.cols.code'), t('help.cols.desc')]} rows={GLOSSARY_PAGES} /></CardBody></Card>
            <Card><CardHeader title={t('help.glossary.editor')} /><CardBody className="!p-0"><Table head={[t('help.cols.zh'), t('help.cols.code'), t('help.cols.desc')]} rows={GLOSSARY_EDITOR} /></CardBody></Card>
            <Card><CardHeader title={t('help.glossary.core')} /><CardBody className="!p-0"><Table head={[t('help.cols.zh'), t('help.cols.en'), t('help.cols.def')]} rows={GLOSSARY_CORE} /></CardBody></Card>
            <Card><CardHeader title={t('help.glossary.status')} /><CardBody className="!p-0"><Table head={[t('help.cols.status'), t('help.cols.color'), t('help.cols.desc')]} rows={GLOSSARY_STATUS} /></CardBody></Card>
          </div>
        ) : null}
        {tab === 'ports' ? (
          <Card>
            <CardHeader title={t('help.tabs.ports')} description={t('help.portsHint')} />
            <CardBody className="!p-0">
              <Table
                head={[t('help.cols.type'), t('help.cols.color'), t('help.cols.usage')]}
                rows={PORT_ROWS.map(([type, color, usage]) => [
                  <span key="t" className="inline-flex items-center gap-2 font-mono text-xs">
                    <span className={`inline-block size-3 border-2 border-surface ${type === 'flow' ? 'rotate-45' : 'rounded-full'}`} style={{ background: PORT_HEX[type] }} />
                    {type}
                  </span>,
                  `${color} ${PORT_HEX[type]}`,
                  usage,
                ])}
              />
            </CardBody>
          </Card>
        ) : null}
        {tab === 'tools' ? <ToolsCatalogue /> : null}
        {tab === 'shortcuts' ? (
          <Card><CardBody className="!p-0"><Table head={[t('help.cols.key'), t('help.cols.action')]} rows={SHORTCUTS.map(([k, v]) => [<kbd key="k" className="rounded border border-line bg-surface-muted px-1.5 py-0.5 font-mono text-xs">{k}</kbd>, v])} /></CardBody></Card>
        ) : null}
        {tab === 'automation' ? (
          <div className="space-y-3">
            <Card>
              <CardBody className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted">{t('integration.subtitle')}</p>
                <Link to="/integration"><Button variant="primary" icon={<Plug size={14} />} data-testid="help-goto-integration">{t('integration.title')}</Button></Link>
              </CardBody>
            </Card>
            {AUTOMATION.map((item) => (
              <Card key={item.title}>
                <CardHeader title={item.title} />
                <CardBody><pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-surface-muted p-3 font-mono text-xs leading-relaxed">{item.code}</pre></CardBody>
              </Card>
            ))}
          </div>
        ) : null}
        {tab === 'accounts' ? (
          <Card>
            <CardHeader title={t('help.tabs.accounts')} />
            <CardBody>
              <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed">
                {ACCOUNTS.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </CardBody>
          </Card>
        ) : null}
      </div>
    </Page>
  )
}
