/**
 * Swagger 風格 API 總覽的純函式：讀伺服器產生的 OpenAPI 描述（/api/openapi.json），
 * 依 tag 分組、從 schema 生成範例 JSON、組出 curl。沒有 React，有單元測試。
 */

export interface OpenApiSchema {
  type?: string
  title?: string
  format?: string
  default?: unknown
  enum?: unknown[]
  items?: OpenApiSchema
  properties?: Record<string, OpenApiSchema>
  required?: string[]
  anyOf?: OpenApiSchema[]
  allOf?: OpenApiSchema[]
  oneOf?: OpenApiSchema[]
  additionalProperties?: boolean | OpenApiSchema
  $ref?: string
  description?: string
}

export interface OpenApiParameter {
  name: string
  in: 'path' | 'query' | 'header' | 'cookie'
  required?: boolean
  schema?: OpenApiSchema
  description?: string
}

export interface OpenApiOperation {
  operationId?: string
  summary?: string
  description?: string
  tags?: string[]
  parameters?: OpenApiParameter[]
  requestBody?: { required?: boolean; content: Record<string, { schema?: OpenApiSchema }> }
  responses?: Record<string, { description?: string; content?: Record<string, { schema?: OpenApiSchema }> }>
}

export interface OpenApiDocument {
  openapi?: string
  info?: { title?: string; version?: string }
  paths: Record<string, Record<string, OpenApiOperation>>
  components?: { schemas?: Record<string, OpenApiSchema> }
}

export type Method = 'get' | 'post' | 'put' | 'patch' | 'delete'
export const METHODS: Method[] = ['get', 'post', 'put', 'patch', 'delete']

export interface Operation {
  /** `method path`，也是 React key */
  id: string
  method: Method
  path: string
  op: OpenApiOperation
  tag: string
}

/** 整合方最常用的端點，排在最前面並附白話說明（i18n 鍵 integration.http.ops.<key>）。 */
export const ESSENTIALS: [Method, string, string][] = [
  ['post', '/api/vision/flows/{flow_id}/run', 'runFlow'],
  ['get', '/api/vision/runs/{run_id}', 'getRun'],
  ['get', '/api/vision/flows', 'listFlows'],
  ['get', '/api/vision/flows/{flow_id}/stats', 'flowStats'],
  ['get', '/api/vision/flows/{flow_id}/spc', 'spc'],
  ['get', '/api/vision/spc/alerts', 'spcAlerts'],
  ['post', '/api/vision/flows/{flow_id}/precision', 'precision'],
  ['post', '/api/vision/flows/{flow_id}/continuous', 'continuous'],
  ['post', '/api/vision/flows/{flow_id}/recipes/{recipe_id}/activate', 'activateRecipe'],
  ['post', '/api/vision/sources/{source_id}/push', 'push'],
  ['get', '/api/vision/images/{ref}', 'image'],
  ['get', '/api/vision/lock', 'lockGet'],
  ['post', '/api/vision/lock', 'lockPost'],
  ['delete', '/api/vision/lock', 'lockDelete'],
  ['get', '/api/vision/summary', 'summary'],
  ['get', '/api/vision/capacity', 'capacity'],
  ['get', '/api/vision/integration/info', 'info'],
]

export function essentialKey(method: Method, path: string): string | undefined {
  return ESSENTIALS.find(([m, p]) => m === method && p === path)?.[2]
}

/** 展平成一份操作清單（照路徑再照方法排）。 */
export function listOperations(doc: OpenApiDocument): Operation[] {
  const out: Operation[] = []
  for (const [path, item] of Object.entries(doc.paths ?? {})) {
    for (const method of METHODS) {
      const op = item[method]
      if (!op) continue
      out.push({ id: `${method} ${path}`, method, path, op, tag: op.tags?.[0] ?? 'other' })
    }
  }
  return out.sort((a, b) => (a.path === b.path ? METHODS.indexOf(a.method) - METHODS.indexOf(b.method) : a.path.localeCompare(b.path)))
}

/** 依 tag 分組，tag 照第一次出現的順序。 */
export function groupByTag(ops: Operation[]): { tag: string; items: Operation[] }[] {
  const groups = new Map<string, Operation[]>()
  for (const op of ops) (groups.get(op.tag) ?? groups.set(op.tag, []).get(op.tag)!).push(op)
  return [...groups].map(([tag, items]) => ({ tag, items }))
}

export function matches(op: Operation, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return `${op.method} ${op.path} ${op.op.summary ?? ''} ${op.op.operationId ?? ''}`.toLowerCase().includes(q)
}

/** 解 $ref（只認 #/components/schemas/X）。 */
export function resolve(schema: OpenApiSchema | undefined, doc: OpenApiDocument): OpenApiSchema | undefined {
  if (!schema?.$ref) return schema
  const name = schema.$ref.split('/').pop() ?? ''
  return doc.components?.schemas?.[name]
}

/** 型別的簡短寫法（integer、string(binary)、array<number>、Foo…）。 */
export function typeOf(schema: OpenApiSchema | undefined, doc: OpenApiDocument, depth = 0): string {
  if (!schema) return ''
  if (schema.$ref) return schema.$ref.split('/').pop() ?? 'object'
  const variants = schema.anyOf ?? schema.oneOf
  if (variants) return variants.map((v) => typeOf(v, doc, depth + 1)).filter((v) => v && v !== 'null').join(' | ') || 'any'
  if (schema.allOf) return typeOf(schema.allOf[0], doc, depth + 1)
  if (schema.enum) return schema.enum.map((v) => JSON.stringify(v)).join(' | ')
  if (schema.type === 'array') return `array<${depth > 3 ? '…' : typeOf(schema.items, doc, depth + 1) || 'any'}>`
  if (schema.type) return schema.format ? `${schema.type}(${schema.format})` : schema.type
  return 'object'
}

/** 從 schema 生成一份可編輯的範例值（required 與有預設值的都填，其餘給型別的空值）。 */
export function exampleFromSchema(schema: OpenApiSchema | undefined, doc: OpenApiDocument, depth = 0): unknown {
  if (!schema || depth > 6) return null
  const s = resolve(schema, doc)
  if (!s) return null
  if (s.default !== undefined) return s.default
  if (s.enum?.length) return s.enum[0]
  const variants = s.anyOf ?? s.oneOf
  if (variants) {
    const first = variants.find((v) => v.type !== 'null') ?? variants[0]
    return exampleFromSchema(first, doc, depth + 1)
  }
  if (s.allOf) return exampleFromSchema(s.allOf[0], doc, depth + 1)
  switch (s.type) {
    case 'string':
      return s.format === 'binary' ? '(file)' : ''
    case 'integer':
    case 'number':
      return 0
    case 'boolean':
      return false
    case 'array':
      return []
    case 'object':
    case undefined: {
      const out: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(s.properties ?? {})) out[k] = exampleFromSchema(v, doc, depth + 1)
      return out
    }
    default:
      return null
  }
}

/** 把 {flow_id} 這種路徑參數換成使用者填的值（空的維持原樣，看得出還沒填）。 */
export function fillPath(path: string, values: Record<string, string>): string {
  return path.replace(/\{(\w+)\}/g, (m, name: string) => (values[name] ? encodeURIComponent(values[name]) : m))
}

export function queryString(values: Record<string, string>): string {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(values)) if (v !== '') qs.set(k, v)
  const s = qs.toString()
  return s ? `?${s}` : ''
}

export interface CurlInput {
  method: Method
  url: string
  keyHeader: string
  contentType?: 'json' | 'multipart'
  body?: string
  form?: Record<string, string>
}

/** Swagger 那種「複製就能貼到終端機」的 curl。 */
export function buildCurl({ method, url, keyHeader, contentType, body, form }: CurlInput): string {
  const lines = [`curl -X ${method.toUpperCase()} "${url}"`, `  -H "${keyHeader}"`]
  if (contentType === 'json' && body !== undefined) {
    lines.push('  -H "Content-Type: application/json"', `  -d '${body.replace(/'/g, "'\\''")}'`)
  } else if (contentType === 'multipart' && form) {
    for (const [k, v] of Object.entries(form)) lines.push(v === '(file)' ? `  -F "${k}=@part.png"` : `  -F '${k}=${v}'`)
  }
  return lines.join(' \\\n')
}
