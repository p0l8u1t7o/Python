import { useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Copy, Cpu, LayoutGrid, List, Plus, Search } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import {
  useBlueprints,
  useDeviceMutations,
  useDevices, useEdgeNodes,
  useSites,
  useUiPreference,
} from '@/lib/queries'
import { errorMessage, fieldErrors } from '@/lib/errors'
import { formatRelative, truncate } from '@/lib/format'
import type { Blueprint, Device, DeviceCredential } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ConnectionBadge,
  DeviceIcon,
  EmptyRow,
  ErrorState,
  Modal,
  PageHeader,
  Pagination,
  SegmentedControl,
  Select,
  SiteTreeSelect,
  Table,
  TBody,
  Td,
  Term,
  TextInput,
  Th,
  THead,
  Tr,
  UNASSIGNED,
} from '@/components/ui'

const PAGE_SIZE = 25

type LayoutMode = 'list' | 'cards'

export function DevicesPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { can } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  const [query, setQuery] = useState(searchParams.get('q') ?? '')
  const [offset, setOffset] = useState(0)
  const [showCreate, setShowCreate] = useState(false)

  const status = searchParams.get('status') ?? ''
  const siteId = searchParams.get('site') ?? ''
  const gatewayId = searchParams.get('gateway') ?? ''
  // Default on: picking a plant almost always means "and everything under it".
  const includeDescendants = searchParams.get('descendants') !== '0'
  const unassignedOnly = searchParams.get('unassigned') === '1'

  // The layout follows the person, not the browser: someone who prefers
  // cards on a wall display should get cards on their laptop too.
  const layout = useUiPreference<{ mode: LayoutMode }>('device-layout', {
    mode: 'list',
  })
  const mode = layout.value.mode

  const sites = useSites()
  const gateways = useEdgeNodes({ include_implicit: false })
  const devices = useDevices({
    edge_node_id: gatewayId || undefined,
    q: searchParams.get('q') ?? undefined,
    status: status || undefined,
    site_id: unassignedOnly ? undefined : siteId || undefined,
    include_descendants: includeDescendants && Boolean(siteId) ? true : undefined,
    unassigned_only: unassignedOnly ? true : undefined,
    limit: PAGE_SIZE,
    offset,
  })

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next, { replace: true })
    setOffset(0)
  }

  function onSearch(event: FormEvent) {
    event.preventDefault()
    setParam('q', query.trim())
  }

  return (
    <>
      <PageHeader
        title={t('devices.title')}
        description={t('devices.subtitle')}
        actions={
          <>
            <SegmentedControl<LayoutMode>
              size="sm"
              value={mode}
              onChange={(next) => layout.save.mutate({ mode: next })}
              options={[
                {
                  value: 'list',
                  label: <List className="size-3.5" />,
                  title: t('devices.layoutList'),
                },
                {
                  value: 'cards',
                  label: <LayoutGrid className="size-3.5" />,
                  title: t('devices.layoutCards'),
                },
              ]}
            />
            {can('device:write') ? (
              <Button
                variant="primary"
                icon={<Plus className="size-4" />}
                onClick={() => setShowCreate(true)}
              >
                {t('devices.register')}
              </Button>
            ) : null}
          </>
        }
      />

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-line p-4">
          <form onSubmit={onSearch} className="flex min-w-56 flex-1 items-end gap-2">
            <TextInput
              label={t('common.search')}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('devices.searchPlaceholder')}
              className="pl-8"
            />
            <Button type="submit" icon={<Search className="size-4" />} aria-label={t('common.search')} />
          </form>

          <Select
            label={t('common.status')}
            value={status}
            placeholder={t('common.all')}
            onChange={(event) => setParam('status', event.target.value)}
            options={[
              { value: 'online', label: t('status.online') },
              { value: 'offline', label: t('status.offline') },
              { value: 'unknown', label: t('status.unknown') },
            ]}
            className="w-36"
          />

          <Select
            label={t('devices.gatewayFilter')}
            value={gatewayId}
            placeholder={t('common.all')}
            onChange={(event) => setParam('gateway', event.target.value)}
            options={(gateways.data?.items ?? []).map((node) => ({
              value: node.id,
              label: node.name && node.name !== node.node_id ? `${node.node_id} · ${node.name}` : node.node_id,
            }))}
            className="w-52"
          />

          <SiteTreeSelect
            label={t('devices.site')}
            sites={sites.data?.items ?? []}
            value={unassignedOnly ? UNASSIGNED : siteId}
            placeholder={t('common.all')}
            allowClear
            allowUnassigned
            onChange={(value) => {
              const next = new URLSearchParams(searchParams)
              next.delete('site')
              next.delete('unassigned')
              if (value === UNASSIGNED) next.set('unassigned', '1')
              else if (value) next.set('site', value)
              setSearchParams(next, { replace: true })
              setOffset(0)
            }}
            className="w-52"
          />

          {siteId && !unassignedOnly ? (
            <div className="pb-1.5">
              <Checkbox
                label={t('devices.includeDescendants')}
                checked={includeDescendants}
                onChange={(value) => setParam('descendants', value ? '' : '0')}
              />
            </div>
          ) : null}
        </div>

        {devices.error ? (
          <ErrorState error={devices.error} onRetry={() => void devices.refetch()} />
        ) : mode === 'cards' ? (
          <>
            {devices.isPending ? (
              <div className="p-4 text-sm text-muted">{t('common.loading')}…</div>
            ) : (devices.data?.items.length ?? 0) === 0 ? (
              <div className="p-8 text-center text-sm text-muted">
                {searchParams.toString() ? t('common.noResults') : t('devices.noDevices')}
              </div>
            ) : (
              <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
                {(devices.data?.items ?? []).map((device) => (
                  <DeviceCard
                    key={device.id}
                    device={device}
                    onOpen={() => navigate(`/devices/${device.id}`)}
                  />
                ))}
              </div>
            )}
            {devices.data ? (
              <Pagination
                total={devices.data.total}
                limit={PAGE_SIZE}
                offset={offset}
                onChange={setOffset}
              />
            ) : null}
          </>
        ) : (
          <>
            <Table>
              <THead>
                <Th>{t('common.status')}</Th>
                <Th>{t('devices.registeredName')}</Th>
                <Th>{t('devices.deviceId')}</Th>
                <Th>{t('devices.site')}</Th>
                <Th>
                  <Term id="blueprint">{t('devices.blueprint')}</Term>
                </Th>
                <Th>{t('common.description')}</Th>
                <Th align="right">{t('devices.lastSeen')}</Th>
              </THead>
              <TBody>
                {devices.isPending ? (
                  <EmptyRow colSpan={7} message={`${t('common.loading')}…`} />
                ) : devices.data && devices.data.items.length > 0 ? (
                  devices.data.items.map((device) => (
                    <Tr key={device.id} onClick={() => navigate(`/devices/${device.id}`)}>
                      <Td>
                        <ConnectionBadge status={device.status} />
                      </Td>
                      <Td>
                        {/* The icon leads the name so the category reads at a
                            glance while scanning the column - which is the
                            whole point of having one. */}
                        <span className="inline-flex items-center gap-2 align-middle">
                          <DeviceIcon category={device.device_category} />
                          <span className="font-medium">{device.name}</span>
                        </span>
                        {!device.is_enabled ? (
                          <Badge tone="neutral" className="ml-2">
                            {t('common.disabled')}
                          </Badge>
                        ) : null}
                        {device.commissioning_state !== 'active' ? (
                          <Badge
                            tone={
                              device.commissioning_state === 'retired'
                                ? 'neutral'
                                : 'warning'
                            }
                            className="ml-2"
                          >
                            {t(`devices.lifecycleStates.${device.commissioning_state}`)}
                          </Badge>
                        ) : null}
                        {device.identity_mismatch ? (
                          <Badge tone="critical" className="ml-2">
                            {t('devices.identityMismatch')}
                          </Badge>
                        ) : null}
                      </Td>
                      <Td className="font-mono text-xs text-muted">{device.device_id}</Td>
                      <Td className="text-muted">{device.site_name ?? '—'}</Td>
                      <Td className="text-muted">
                        {device.device_type_name ?? '—'}
                        {device.device_category ? (
                          <span className="ml-1.5 text-xs text-subtle">
                            {t(`devices.categories.${device.device_category}`, {
                              defaultValue: device.device_category,
                            })}
                          </span>
                        ) : null}
                      </Td>
                      <Td className="max-w-56 text-muted">
                        {device.description ? (
                          <span className="block truncate" title={device.description}>
                            {device.description}
                          </span>
                        ) : (
                          '—'
                        )}
                      </Td>
                      <Td align="right" className="whitespace-nowrap text-muted">
                        {device.last_seen_at ? formatRelative(device.last_seen_at) : t('common.never')}
                      </Td>
                    </Tr>
                  ))
                ) : (
                  <EmptyRow
                    colSpan={6}
                    message={
                      searchParams.toString() ? t('common.noResults') : t('devices.noDevices')
                    }
                  />
                )}
              </TBody>
            </Table>

            {devices.data ? (
              <Pagination
                total={devices.data.total}
                limit={PAGE_SIZE}
                offset={offset}
                onChange={setOffset}
              />
            ) : null}
          </>
        )}
      </Card>

      <RegisterDeviceModal open={showCreate} onClose={() => setShowCreate(false)} />
    </>
  )
}

function RegisterDeviceModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const sites = useSites()
  const blueprints = useBlueprints()
  const { create } = useDeviceMutations()

  const [form, setForm] = useState({
    device_id: '',
    name: '',
    site_id: '',
    device_type_id: '',
    serial_number: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [credential, setCredential] = useState<DeviceCredential | null>(null)

  function reset() {
    setForm({ device_id: '', name: '', site_id: '', device_type_id: '', serial_number: '' })
    setErrors({})
    setCredential(null)
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setErrors({})
    try {
      const result = await create.mutateAsync({
        device_id: form.device_id.trim(),
        name: form.name.trim(),
        site_id: form.site_id || null,
        device_type_id: form.device_type_id || null,
        serial_number: form.serial_number.trim(),
      })
      // The password exists only in this response, so the dialog switches to
      // showing it rather than closing.
      setCredential(result.credential)
    } catch (error) {
      setErrors(fieldErrors(error))
      toast.error(errorMessage(error))
    }
  }

  if (credential) {
    return (
      <Modal
        open={open}
        onClose={() => {
          reset()
          onClose()
        }}
        title={t('devices.credentialsIssued')}
        description={t('devices.credentialWarning')}
        footer={
          <Button
            variant="primary"
            onClick={() => {
              reset()
              onClose()
            }}
          >
            {t('common.close')}
          </Button>
        }
      >
        <CredentialPanel credential={credential} />
      </Modal>
    )
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        reset()
        onClose()
      }}
      title={t('devices.register')}
      description={t('devices.registerHint')}
      footer={
        <>
          <Button
            onClick={() => {
              reset()
              onClose()
            }}
          >
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={!form.device_id || !form.name}
            onClick={(event) => onSubmit(event as unknown as FormEvent)}
          >
            {t('common.create')}
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <TextInput
          label={t('devices.deviceId')}
          required
          value={form.device_id}
          error={errors.device_id}
          onChange={(event) => setForm({ ...form, device_id: event.target.value })}
          placeholder="ZQS-BESS-0001"
          className="font-mono"
        />
        <TextInput
          label={t('devices.registeredName')}
          required
          value={form.name}
          error={errors.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          placeholder="BESS #1"
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <SiteTreeSelect
            label={t('devices.site')}
            sites={sites.data?.items ?? []}
            value={form.site_id}
            placeholder={t('common.none')}
            allowClear
            hint={t('devices.siteHint')}
            onChange={(value) => setForm({ ...form, site_id: value })}
          />
          <BlueprintPicker
            label={<Term id="blueprint">{t('devices.blueprint')}</Term>}
            blueprints={blueprints.data ?? []}
            value={form.device_type_id}
            error={errors.device_type_id}
            onChange={(value) => setForm({ ...form, device_type_id: value })}
          />
        </div>
        <TextInput
          label={t('devices.serialNumber')}
          value={form.serial_number}
          error={errors.serial_number}
          hint={t('devices.serialHint')}
          onChange={(event) => setForm({ ...form, serial_number: event.target.value })}
        />
      </form>
    </Modal>
  )
}

/**
 * One device as a card.
 *
 * The same facts as the table row, laid out for scanning a wall rather than
 * reading a column: status and category first, then the identifiers, then
 * whatever the operator wrote in the description - which is usually where
 * "the one behind the compressor" lives.
 */
function DeviceCard({ device, onOpen }: { device: Device; onOpen: () => void }) {
  const { t } = useTranslation()

  return (
    <button
      type="button"
      onClick={onOpen}
      className="card w-full p-4 text-left transition-colors hover:border-line-strong hover:bg-surface-muted/50"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          <DeviceIcon category={device.device_category} className="size-5" />
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">{device.name}</span>
            <span className="block truncate font-mono text-[11px] text-subtle">
              {device.device_id}
            </span>
          </span>
        </span>
        <ConnectionBadge status={device.status} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {device.device_category ? (
          <Badge tone="neutral">
            {t(`devices.categories.${device.device_category}`, {
              defaultValue: device.device_category,
            })}
          </Badge>
        ) : null}
        {!device.is_enabled ? (
          <Badge tone="neutral">{t('common.disabled')}</Badge>
        ) : null}
        {device.commissioning_state !== 'active' ? (
          <Badge tone={device.commissioning_state === 'retired' ? 'neutral' : 'warning'}>
            {t(`devices.lifecycleStates.${device.commissioning_state}`)}
          </Badge>
        ) : null}
        {device.identity_mismatch ? (
          <Badge tone="critical">{t('devices.identityMismatch')}</Badge>
        ) : null}
      </div>

      {device.description ? (
        <p className="mt-2 line-clamp-2 text-xs text-muted">
          {truncate(device.description, 120)}
        </p>
      ) : null}

      <dl className="mt-3 space-y-1 border-t border-line pt-2 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-subtle">{t('devices.site')}</dt>
          <dd className="min-w-0 truncate text-muted">{device.site_name ?? '—'}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-subtle">{t('devices.blueprint')}</dt>
          <dd className="min-w-0 truncate text-muted">{device.device_type_name ?? '—'}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-subtle">{t('devices.lastSeen')}</dt>
          <dd className="text-muted">
            {device.last_seen_at ? formatRelative(device.last_seen_at) : t('common.never')}
          </dd>
        </div>
      </dl>
    </button>
  )
}

/**
 * Blueprint picker that explains what it is offering.
 *
 * A blueprint decides the device's category, and **a category never changes
 * after commissioning** - getting it wrong means registering a replacement,
 * not editing a field. That makes this the one dropdown on the page where a
 * sentence of explanation earns its space.
 */
export function BlueprintPicker({
  blueprints,
  value,
  onChange,
  label,
  error,
}: {
  blueprints: Blueprint[]
  value: string
  onChange: (value: string) => void
  label?: ReactNode
  error?: string
}) {
  const { t } = useTranslation()
  const selected = blueprints.find((blueprint) => blueprint.id === value)
  const categoryHelp = selected?.category
    ? t(`devices.categoryHelp.${selected.category}`, { defaultValue: '' })
    : ''

  return (
    <div>
      <Select
        label={label}
        value={value}
        placeholder={t('common.none')}
        error={error}
        onChange={(event) => onChange(event.target.value)}
        options={blueprints.map((blueprint) => ({
          value: blueprint.id,
          label: blueprint.label || blueprint.name,
        }))}
      />
      {selected ? (
        <div className="mt-2 rounded-lg bg-surface-muted p-2.5">
          <p className="flex items-center gap-1.5 text-xs font-medium text-content">
            <DeviceIcon category={selected.category} className="size-3.5" />
            {t(`devices.categories.${selected.category}`, {
              defaultValue: selected.category,
            })}
          </p>
          {selected.description_text ? (
            <p className="mt-1 text-xs text-muted">{selected.description_text}</p>
          ) : null}
          {categoryHelp ? (
            <p className="mt-1 text-xs text-subtle">{categoryHelp}</p>
          ) : null}
          <p className="mt-1.5 text-[11px] text-subtle">
            {t('devices.categoryImmutable')}
          </p>
        </div>
      ) : (
        <p className="hint">{t('devices.blueprintPickHint')}</p>
      )}
    </div>
  )
}

export function CredentialPanel({ credential }: { credential: DeviceCredential }) {
  const { t } = useTranslation()
  const toast = useToast()

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      toast.success(t('common.copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  const rows: { label: string; value: string }[] = [
    { label: 'Username', value: credential.mqtt_username },
    ...(credential.mqtt_password ? [{ label: 'Password', value: credential.mqtt_password }] : []),
  ]

  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center gap-2 rounded-lg bg-surface-muted p-2.5">
          <span className="w-20 shrink-0 text-xs font-medium text-muted">{row.label}</span>
          <code className="min-w-0 flex-1 truncate font-mono text-xs text-content">{row.value}</code>
          <Button
            size="sm"
            icon={<Copy className="size-3.5" />}
            onClick={() => void copy(row.value)}
            aria-label={t('common.copy')}
          />
        </div>
      ))}
      <p className="hint flex items-start gap-1.5">
        <Cpu className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span>{t('devices.credentialWarning')}</span>
      </p>
    </div>
  )
}
