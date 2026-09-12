import { readFile, mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const webRoot = path.resolve(scriptDirectory, '..')
const schemaRoot = path.resolve(webRoot, '../../packages/schemas/json/v1')
const outputPath = path.resolve(webRoot, 'src/generated/contracts.ts')
const contracts = [
  ['ProjectContract', 'project.schema.json'],
  ['FrameTreeContract', 'frame-tree.schema.json'],
  ['ArtifactContract', 'artifact.schema.json'],
  ['AuditEventContract', 'audit-event.schema.json'],
  ['ChangeSetContract', 'change-set.schema.json'],
  ['ChangeSetPreviewContract', 'change-set-preview.schema.json'],
  ['ChangeSetApplyResultContract', 'change-set-apply-result.schema.json'],
  ['JobContract', 'job.schema.json'],
  ['JobSubmitContract', 'job-submit.schema.json'],
  ['ProcessSpecContract', 'process-spec.schema.json'],
  ['ProcessAnalysisContract', 'process-analysis.schema.json'],
  ['MotionSpecContract', 'motion-spec.schema.json'],
  ['SceneAssemblyContract', 'scene-assembly-spec.schema.json'],
  ['ValidationReportContract', 'validation-report.schema.json'],
  ['ReleaseManifestContract', 'release-manifest.schema.json'],
  ['ReleaseRequestContract', 'release-request.schema.json'],
  ['RevisionDiffContract', 'revision-diff.schema.json'],
  ['ReviewCommentContract', 'review-comment.schema.json'],
]

let output = '// Generated from versioned Pydantic JSON Schema. Do not edit manually.\n\n'
for (const [namespace, filename] of contracts) {
  const schema = JSON.parse(await readFile(path.join(schemaRoot, filename), 'utf8'))
  const declaration = await compile(schema, schema.title, {
    bannerComment: '',
    unknownAny: false,
  })
  const indented = declaration
    .trim()
    .split('\n')
    .map((line) => `  ${line}`)
    .join('\n')
  output += `export namespace ${namespace} {\n${indented}\n}\n\n`
}

await mkdir(path.dirname(outputPath), { recursive: true })
await writeFile(outputPath, output, 'utf8')
