import { api, type Project } from './api'

interface ModelContext {
  registerTool(
    tool: {
      name: string
      title: string
      description: string
      inputSchema: object
      annotations: { readOnlyHint: boolean; untrustedContentHint: boolean }
      execute(input: unknown): Promise<object>
    },
    options: { signal: AbortSignal },
  ): void | Promise<void>
}

declare global {
  interface Document {
    readonly modelContext?: ModelContext
  }
}

interface CreateProjectInput {
  name: string
  customerName: string
}

function validateCreateProjectInput(input: unknown): CreateProjectInput {
  if (typeof input !== 'object' || input === null) {
    throw new TypeError('Input must be an object')
  }
  const candidate = input as Record<string, unknown>
  if (typeof candidate.name !== 'string' || candidate.name.trim().length === 0) {
    throw new TypeError('name must be a non-empty string')
  }
  if (candidate.name.length > 200) {
    throw new TypeError('name must not exceed 200 characters')
  }
  if (candidate.customerName !== undefined && typeof candidate.customerName !== 'string') {
    throw new TypeError('customerName must be a string')
  }
  if (typeof candidate.customerName === 'string' && candidate.customerName.length > 200) {
    throw new TypeError('customerName must not exceed 200 characters')
  }
  return {
    name: candidate.name.trim(),
    customerName: typeof candidate.customerName === 'string' ? candidate.customerName : '',
  }
}

export function registerCreateProjectTool(onCreated: (project: Project) => void): () => void {
  const context = document.modelContext
  if (!context?.registerTool) return () => undefined

  const lifecycle = new AbortController()
  void Promise.resolve(
    context.registerTool(
      {
        name: 'create_project',
        title: '建立數位分身專案',
        description: '建立專案與第一個 DRAFT revision，並在目前工作台顯示結果。',
        inputSchema: {
          type: 'object',
          properties: {
            name: { type: 'string', minLength: 1, maxLength: 200 },
            customerName: { type: 'string', maxLength: 200 },
          },
          required: ['name'],
          additionalProperties: false,
        },
        annotations: { readOnlyHint: false, untrustedContentHint: false },
        async execute(input) {
          const values = validateCreateProjectInput(input)
          const project = await api.createProject(values.name, values.customerName)
          onCreated(project)
          return {
            projectId: project.id,
            revisionId: project.current_revision.id,
            revisionStatus: project.current_revision.status,
          }
        },
      },
      { signal: lifecycle.signal },
    ),
  ).catch((error: unknown) => console.warn('WebMCP tool registration failed', error))

  return () => lifecycle.abort()
}

