/** 整合 ▸ 回傳格式：RunReport 欄位與錯誤碼對照。 */
import { useTranslation } from 'react-i18next'

import { CodeBlock } from './shared'
import { Card, CardBody, CardHeader } from '@/components/ui'

const RUN_REPORT_FIELDS: [string, string, string][] = [
  ['id', 'string', 'The run id (a uuid hex)'],
  ['flow_id / flow_version', 'int', 'The flow, and its version at run time'],
  ['trigger', 'string', 'ui / api / tcp / continuous / preview / integration…'],
  ['status', '"ok" | "ng" | "failed" | "cancelled"', 'OK and NG are verdicts; failed means a tool error, a timeout or no image'],
  ['started_at / finished_at', 'float', 'Unix seconds'],
  ['duration_ms', 'float', 'Total duration'],
  ['error', 'string', 'Why it failed (an empty string on success)'],
  ['outputs', 'object', 'The named outputs (see below)'],
  ['nodes', 'object', 'Per step: {status, duration_ms, message, branch, outputs, overlays, detail, logs}'],
  ['persisted', 'bool', 'true means it came from the database history (GET /runs/{id})'],
]

const ERROR_CODES: [string, string, string][] = [
  ['engine_locked', '423', 'The engine is locked; details is the lock object'],
  ['flow_queue_full', '429', 'That flow already has VISION_MAX_QUEUE_PER_FLOW triggers waiting (16 by default); a flow runs one run at a time'],
  ['run_timeout', '504', 'Waited longer than timeout_s; details.run_id collects the result afterwards, and the run itself is not aborted'],
  ['flow_disabled', '409', 'The flow is disabled, so an external trigger is refused'],
  ['flow_not_found', '404', 'No such flow id, or no permission'],
  ['run_not_found', '404', 'The run is in neither memory nor the database'],
  ['image_gone', '404', 'The image ref has been evicted from the cache (KEEP_RUN_IMAGES)'],
  ['bad_image', '422', 'The image cannot be decoded'],
  ['too_many_images', '422', 'A batch test over 50 images'],
  ['validation_error', '422', 'An invalid parameter'],
  ['unauthenticated / unauthorized', '401', 'A missing or invalid token or API key'],
  ['permission_denied / not_owner', '403', 'No permission to modify'],
  ['capacity', '503', 'The thread pool is full'],
]

/** TCP 一行指令的失敗碼（設備請用 code 分支，說明文字會隨版本潤飾）。 */
const TCP_CODES: [string, string][] = [
  ['empty_command', 'A blank line'],
  ['unknown_command', 'Unrecognised command'],
  ['missing_argument', 'The command is missing a flow id or name'],
  ['bad_argument', 'An argument is not key=value (quote values containing spaces)'],
  ['flow_not_found', 'No such flow id or name'],
  ['flow_disabled', 'The flow is disabled'],
  ['flow_queue_full', 'That flow already has the maximum number of triggers waiting'],
  ['recipe_not_found', 'The recipe named by recipe= does not exist'],
  ['internal_error', 'A server exception, recorded in the log'],
]

function FormatSection() {
  const { t } = useTranslation()
  const head = (cols: string[]) => (
    <thead><tr>{cols.map((c) => <th key={c} className="table-header">{c}</th>)}</tr></thead>
  )
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t('integration.format.runReport')} />
        <CardBody className="!p-0">
          <table className="w-full text-sm">
            {head([t('integration.format.cols.field'), t('integration.format.cols.type'), t('integration.format.cols.desc')])}
            <tbody className="divide-y divide-line">{RUN_REPORT_FIELDS.map(([f, ty, d]) => <tr key={f}><td className="table-cell font-mono text-xs">{f}</td><td className="table-cell font-mono text-xs text-muted">{ty}</td><td className="table-cell">{d}</td></tr>)}</tbody>
          </table>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('integration.format.outputs')} description={t('integration.format.outputsHint')} />
        <CardBody>
          <CodeBlock code={`{\n  "status": "ng",\n  "outputs": {\n    "hole_count": 3,\n    "judge": "NG",\n    "result_image": {"ref": "run:abc:n5:image", "width": 640, "height": 480}\n  },\n  "duration_ms": 12.3\n}`} />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('integration.format.tcpErrors')} description={t('integration.format.tcpErrorsHint')} />
        <CardBody className="!p-0">
          <table className="w-full text-sm">
            {head([t('integration.format.cols.field'), t('integration.format.cols.desc')])}
            <tbody className="divide-y divide-line">{TCP_CODES.map(([c, d]) => <tr key={c}><td className="table-cell font-mono text-xs">{c}</td><td className="table-cell">{d}</td></tr>)}</tbody>
          </table>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('integration.format.errors')} />
        <CardBody className="!p-0">
          <table className="w-full text-sm">
            {head([t('integration.format.cols.code'), t('integration.format.cols.http'), t('integration.format.cols.when')])}
            <tbody className="divide-y divide-line">{ERROR_CODES.map(([c, h, w]) => <tr key={c}><td className="table-cell font-mono text-xs">{c}</td><td className="table-cell tnum">{h}</td><td className="table-cell">{w}</td></tr>)}</tbody>
          </table>
          <p className="px-4 py-3 text-xs text-muted">{'{"error": {"code": "...", "message": "...", "details": ...}}'}</p>
        </CardBody>
      </Card>
    </div>
  )
}


export function FormatPage() {
  return (
    <div className="space-y-4">
      <FormatSection />
      
    </div>
  )
}
