/** API 總覽的純函式：分組、範例生成、路徑填值、curl。 */
import { describe, expect, it } from 'vitest'

import { buildCurl, essentialKey, exampleFromSchema, fillPath, groupByTag, listOperations, matches, queryString, typeOf, type OpenApiDocument } from './openapi'

const doc: OpenApiDocument = {
  paths: {
    '/api/vision/flows/{flow_id}/run': {
      post: { summary: 'Run Flow', tags: ['vision'], parameters: [{ name: 'flow_id', in: 'path', required: true, schema: { type: 'integer' } }, { name: 'wait', in: 'query', schema: { type: 'boolean', default: true } }],
        requestBody: { content: { 'multipart/form-data': { schema: { properties: { image: { anyOf: [{ type: 'string', format: 'binary' }, { type: 'null' }] }, context: { anyOf: [{ type: 'string' }, { type: 'null' }] } } } } } } },
    },
    '/api/vision/lock': {
      get: { summary: 'Get Lock', tags: ['lock'] },
      post: { summary: 'Acquire Lock', tags: ['lock'], requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/LockIn' } } } } },
    },
    '/api/auth/me': { get: { summary: 'Me', tags: ['auth'] } },
  },
  components: { schemas: { LockIn: { type: 'object', properties: { reason: { type: 'string', default: '' }, ttl_s: { anyOf: [{ type: 'integer' }, { type: 'null' }] }, tags: { type: 'array', items: { type: 'string' } } }, required: ['reason'] } } },
}

describe('openapi helpers', () => {
  it('lists operations sorted by path then method and groups them by tag', () => {
    const ops = listOperations(doc)
    expect(ops.map((o) => o.id)).toEqual(['get /api/auth/me', 'get /api/vision/flows/{flow_id}/run'.replace('get', 'post'), 'get /api/vision/lock', 'post /api/vision/lock'])
    expect(groupByTag(ops).map((g) => [g.tag, g.items.length])).toEqual([['auth', 1], ['vision', 1], ['lock', 2]])
    expect(essentialKey('post', '/api/vision/flows/{flow_id}/run')).toBe('runFlow')
    expect(essentialKey('get', '/api/auth/me')).toBeUndefined()
    expect(ops.filter((o) => matches(o, 'LOCK')).length).toBe(2)
    expect(ops.filter((o) => matches(o, 'run flow')).length).toBe(1)
  })

  it('builds an editable example from a schema, following $ref and anyOf', () => {
    expect(exampleFromSchema({ $ref: '#/components/schemas/LockIn' }, doc)).toEqual({ reason: '', ttl_s: 0, tags: [] })
    const multipart = doc.paths['/api/vision/flows/{flow_id}/run'].post.requestBody!.content['multipart/form-data'].schema
    expect(exampleFromSchema(multipart, doc)).toEqual({ image: '(file)', context: '' })
    expect(typeOf({ anyOf: [{ type: 'integer' }, { type: 'null' }] }, doc)).toBe('integer')
    expect(typeOf({ type: 'array', items: { type: 'string' } }, doc)).toBe('array<string>')
    expect(typeOf({ $ref: '#/components/schemas/LockIn' }, doc)).toBe('LockIn')
  })

  it('fills path parameters, keeps the placeholder when blank, and builds curl', () => {
    expect(fillPath('/api/vision/flows/{flow_id}/run', { flow_id: '7' })).toBe('/api/vision/flows/7/run')
    expect(fillPath('/api/vision/images/{ref}', {})).toBe('/api/vision/images/{ref}')
    expect(fillPath('/api/vision/images/{ref}', { ref: 'run:a b' })).toBe('/api/vision/images/run%3Aa%20b')
    expect(queryString({ wait: '1', timeout_s: '' })).toBe('?wait=1')
    const curl = buildCurl({ method: 'post', url: 'http://h/api/vision/lock', keyHeader: 'X-API-Key: K', contentType: 'json', body: '{"reason": "it\'s"}' })
    expect(curl).toContain('curl -X POST "http://h/api/vision/lock"')
    expect(curl).toContain(`-d '{"reason": "it'\\''s"}'`)
    const form = buildCurl({ method: 'post', url: 'http://h/run', keyHeader: 'X-API-Key: K', contentType: 'multipart', form: { image: '(file)', context: '{}' } })
    expect(form).toContain('-F "image=@part.png"')
    expect(form).toContain("-F 'context={}'")
  })
})
