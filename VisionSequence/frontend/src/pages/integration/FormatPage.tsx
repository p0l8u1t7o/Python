/** 整合 ▸ 回傳格式：RunReport 欄位與錯誤碼對照。 */
import { useTranslation } from 'react-i18next'

import { CodeBlock } from './shared'
import { Card, CardBody, CardHeader } from '@/components/ui'

const RUN_REPORT_FIELDS: [string, string, string][] = [
  ['id', 'string', 'run id（uuid hex）'],
  ['flow_id / flow_version', 'int', '流程與執行時的版本'],
  ['trigger', 'string', 'ui / api / tcp / continuous / preview / integration…'],
  ['status', '"ok" | "ng" | "failed" | "cancelled"', 'OK／NG 為判定結果；failed 為工具錯誤、逾時或沒有影像'],
  ['started_at / finished_at', 'float', 'Unix 秒'],
  ['duration_ms', 'float', '總耗時'],
  ['error', 'string', '失敗原因（成功為空字串）'],
  ['outputs', 'object', '具名輸出（見下表）'],
  ['nodes', 'object', '每個步驟的 {status, duration_ms, message, branch, outputs, overlays, detail, logs}'],
  ['persisted', 'bool', 'true = 來自資料庫歷史（GET /runs/{id}）'],
]

const ERROR_CODES: [string, string, string][] = [
  ['engine_locked', '423', '引擎被鎖定；details 是 lock 物件'],
  ['flow_queue_full', '429', '該流程等待中的觸發已達 VISION_MAX_QUEUE_PER_FLOW（預設 16）；每個流程一次只跑一個 run'],
  ['run_timeout', '504', '等結果超過 timeout_s；details.run_id 可事後取結果，執行本身不會被中止'],
  ['flow_disabled', '409', '流程已停用（外部觸發被拒）'],
  ['flow_not_found', '404', 'flow id 不存在或無權限'],
  ['run_not_found', '404', 'run 不在記憶體也不在資料庫'],
  ['image_gone', '404', '影像 ref 已被快取淘汰（KEEP_RUN_IMAGES）'],
  ['bad_image', '422', '無法解碼影像'],
  ['too_many_images', '422', '批次測試超過 50 張'],
  ['validation_error', '422', '參數不合法'],
  ['unauthenticated / unauthorized', '401', '缺少或錯誤的權杖／API 金鑰'],
  ['permission_denied / not_owner', '403', '沒有修改權限'],
  ['capacity', '503', '執行緒池已滿'],
]

/** TCP 一行指令的失敗碼（設備請用 code 分支，中文說明會隨版本潤飾）。 */
const TCP_CODES: [string, string][] = [
  ['empty_command', '空白行'],
  ['unknown_command', '不認得的指令'],
  ['missing_argument', '指令少了流程 id 或名稱'],
  ['bad_argument', '引數不是 key=value（值含空白要加引號）'],
  ['flow_not_found', '流程 id／名稱不存在'],
  ['flow_disabled', '流程已停用'],
  ['flow_queue_full', '該流程等待中的觸發已達上限'],
  ['recipe_not_found', 'recipe= 指定的配方不存在'],
  ['internal_error', '伺服器例外，記錄在日誌'],
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
