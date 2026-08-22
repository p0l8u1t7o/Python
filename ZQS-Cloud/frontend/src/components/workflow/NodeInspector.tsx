import { useTranslation } from 'react-i18next'

import { useAllDevices, useDevice, useMetrics, useWorkflowList } from '@/lib/queries'
import type { GraphNode, NodeParam, NodeTypeDef } from '@/lib/workflowTypes'
import { nodeProblems } from '@/lib/workflowValidation'
import { Checkbox, Select, TextArea, TextInput } from '@/components/ui'

/** A small palette that reads in both themes; free choice via the picker. */
const NODE_COLORS = [
  '#0f766e', '#1d4ed8', '#7c3aed', '#b45309',
  '#be123c', '#0891b2', '#4d7c0f', '#334155',
]

function ColorField({
  value,
  onChange,
  label,
  clearLabel,
}: {
  value: string
  onChange: (color: string) => void
  label: string
  clearLabel: string
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted">{label}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {NODE_COLORS.map((color) => (
          <button
            key={color}
            type="button"
            aria-label={color}
            onClick={() => onChange(color)}
            className={`size-5 rounded-full border ${
              value === color ? 'ring-2 ring-brand ring-offset-1' : 'border-line'
            }`}
            style={{ background: color }}
          />
        ))}
        <input
          type="color"
          value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : '#0f766e'}
          onChange={(event) => onChange(event.target.value)}
          className="size-6 cursor-pointer rounded border border-line bg-transparent p-0"
          title={label}
        />
        {value ? (
          <button
            type="button"
            onClick={() => onChange('')}
            className="text-[11px] text-muted hover:underline"
          >
            {clearLabel}
          </button>
        ) : null}
      </div>
    </div>
  )
}

/**
 * One parameter field, rendered from the server's declaration.
 *
 * The kinds are a small closed vocabulary rather than free JSON Schema, and
 * this switch is the reason: every kind has to be renderable here, so a node
 * type cannot declare a parameter nobody can fill in.
 */
function ParamField({
  param,
  value,
  onChange,
  deviceId,
}: {
  param: NodeParam
  value: unknown
  onChange: (value: unknown) => void
  /** The node's own device, for narrowing metric and command pickers. */
  deviceId?: string
}) {
  const { t } = useTranslation()
  const devices = useAllDevices({ enabled: param.kind === 'device' })
  const metrics = useMetrics()
  const workflows = useWorkflowList({ enabled: param.kind === 'workflow' })
  // The command list lives on the device *detail*, not on the list row,
  // and it has to: it is the blueprint's command catalogue, which the
  // list endpoint deliberately does not carry for every device.
  const device = useDevice(param.kind === 'command' ? deviceId || undefined : undefined)

  const text = value === null || value === undefined ? '' : String(value)

  switch (param.kind) {
    case 'boolean':
      return (
        <Checkbox
          label={param.label}
          hint={param.help_text}
          checked={Boolean(value)}
          onChange={onChange}
        />
      )

    case 'number':
    case 'duration':
      return (
        <TextInput
          label={param.label}
          type="number"
          required={param.required}
          suffix={param.unit || undefined}
          min={param.minimum ?? undefined}
          max={param.maximum ?? undefined}
          hint={param.help_text}
          value={text}
          onChange={(event) =>
            onChange(event.target.value === '' ? null : Number(event.target.value))
          }
        />
      )

    case 'select':
      return (
        <Select
          label={param.label}
          required={param.required}
          hint={param.help_text}
          value={text}
          placeholder={param.required ? undefined : t('common.none')}
          onChange={(event) => onChange(event.target.value)}
          options={param.options}
        />
      )

    case 'device':
      return (
        <Select
          label={param.label}
          required={param.required}
          hint={param.help_text}
          value={text}
          placeholder={t('common.none')}
          onChange={(event) => onChange(event.target.value)}
          options={(devices.data?.items ?? []).map((device) => ({
            value: device.id,
            label: device.name || device.device_id,
          }))}
        />
      )

    case 'metric':
      return (
        <Select
          label={param.label}
          required={param.required}
          hint={param.help_text}
          value={text}
          placeholder={t('common.none')}
          onChange={(event) => onChange(event.target.value)}
          options={(metrics.data ?? []).map((metric) => ({
            value: metric.key,
            label: metric.unit ? `${metric.key} (${metric.unit})` : metric.key,
          }))}
        />
      )

    case 'command': {
      // Offered from the selected device's own blueprint, so the list cannot
      // contain a command that device will refuse.
      const available = device.data?.available_commands ?? []
      if (available.length === 0) {
        return (
          <TextInput
            label={param.label}
            required={param.required}
            hint={t('workflows.commandFreeTextHint')}
            value={text}
            onChange={(event) => onChange(event.target.value)}
          />
        )
      }
      return (
        <Select
          label={param.label}
          required={param.required}
          hint={param.help_text}
          value={text}
          placeholder={t('common.none')}
          onChange={(event) => onChange(event.target.value)}
          options={available.map((command) => ({
            value: command.name,
            // `label` is a translation map, so fall back to the wire name
            // rather than rendering "[object Object]".
            label: command.label?.[t('common.localeKey', { defaultValue: 'en' })]
              ?? command.label?.en
              ?? command.name,
          }))}
        />
      )
    }

    case 'workflow':
      return (
        <Select
          label={param.label}
          required={param.required}
          hint={param.help_text}
          value={text}
          placeholder={t('common.none')}
          onChange={(event) => onChange(event.target.value)}
          options={(workflows.data?.items ?? []).map((workflow) => ({
            value: workflow.id,
            label: workflow.name,
          }))}
        />
      )

    default:
      return (
        <TextInput
          label={param.label}
          required={param.required}
          hint={param.help_text}
          value={text}
          onChange={(event) => onChange(event.target.value)}
        />
      )
  }
}

/**
 * The panel for whichever node is selected.
 *
 * Name, note and on/off sit above the parameters and apply to every node type,
 * because they are what makes a canvas readable six months later: a graph of
 * boxes labelled "IF-End" is a graph nobody can maintain.
 */
export function NodeInspector({
  node,
  definition,
  onChange,
  onDelete,
}: {
  node: GraphNode
  definition: NodeTypeDef | undefined
  onChange: (patch: Partial<GraphNode>) => void
  onDelete: () => void
}) {
  const { t } = useTranslation()
  const params = node.params ?? {}
  const isNote = node.type === 'note'
  const isArrow = node.type === 'arrow'
  const problems = isNote || isArrow ? [] : nodeProblems(node, definition)
  const problemByParam = new Map(problems.map((problem) => [problem.paramKey, problem]))

  const typeLabel = definition
    ? t(`workflows.nodeTypes.${definition.key}.label`, { defaultValue: definition.label })
    : node.type
  const typeDescription = definition
    ? t(`workflows.nodeTypes.${definition.key}.description`, {
        defaultValue: definition.description,
      })
    : ''

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-medium">{typeLabel}</p>
        {typeDescription ? (
          <p className="mt-1 text-xs text-muted">{typeDescription}</p>
        ) : null}
      </div>

      {isArrow ? null : (
      <TextInput
        label={isNote ? t('workflows.noteTitle') : t('workflows.nodeName')}
        value={node.label ?? ''}
        placeholder={typeLabel}
        hint={isNote ? undefined : t('workflows.nodeNameHint')}
        onChange={(event) => onChange({ label: event.target.value })}
      />
      )}

      {isArrow ? null : (
      <TextArea
        label={isNote ? t('workflows.noteText') : t('workflows.nodeNote')}
        rows={isNote ? 5 : 2}
        value={node.description ?? ''}
        hint={isNote ? undefined : t('workflows.nodeNoteHint')}
        onChange={(event) => onChange({ description: event.target.value })}
      />
      )}

      <ColorField
        label={t('workflows.nodeColor')}
        clearLabel={t('workflows.nodeColorReset')}
        value={node.color ?? ''}
        onChange={(color) => onChange({ color })}
      />

      {isNote || isArrow ? null : (
        <>
          <Checkbox
            label={t('workflows.nodeEnabled')}
            hint={t('workflows.nodeEnabledHint')}
            checked={node.enabled !== false}
            onChange={(enabled) => onChange({ enabled })}
          />

          <Checkbox
            label={t('workflows.breakpoint')}
            hint={t('workflows.breakpointHint')}
            checked={node.breakpoint === true}
            onChange={(breakpoint) => onChange({ breakpoint })}
          />

          <div className="space-y-3 border-t border-line pt-3">
            <p className="text-xs font-medium text-muted">{t('workflows.parameters')}</p>
            {(definition?.params ?? []).length === 0 ? (
              <p className="text-xs text-muted">{t('workflows.noParameters')}</p>
            ) : (
              (definition?.params ?? []).map((param) => {
                const problem = problemByParam.get(param.key)
                return (
                  <div key={param.key}>
                    <ParamField
                      param={param}
                      value={params[param.key] ?? param.default}
                      deviceId={String(params.device_id ?? '')}
                      onChange={(value) =>
                        onChange({ params: { ...params, [param.key]: value } })
                      }
                    />
                    {problem ? (
                      <p className="mt-1 text-[11px] text-critical">
                        {t(`workflows.validation.${problem.code}`, problem.values)}
                      </p>
                    ) : null}
                  </div>
                )
              })
            )}
          </div>
        </>
      )}

      {isArrow ? (
        <div className="space-y-3 border-t border-line pt-3">
          {(definition?.params ?? []).map((param) => (
            <ParamField
              key={param.key}
              param={param}
              value={params[param.key] ?? param.default}
              onChange={(value) =>
                onChange({ params: { ...params, [param.key]: value } })
              }
            />
          ))}
        </div>
      ) : null}

      <div className="border-t border-line pt-3">
        <p className="mb-2 font-mono text-[11px] text-muted">id: {node.id}</p>
        <button
          type="button"
          onClick={onDelete}
          className="text-xs text-critical hover:underline"
        >
          {t('workflows.deleteNode')}
        </button>
      </div>
    </div>
  )
}
