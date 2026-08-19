import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Copy, Cpu, Plus, Search } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { useBlueprints, useDeviceMutations, useDevices, useSites } from '@/lib/queries'
import { errorMessage, fieldErrors } from '@/lib/errors'
import { formatRelative } from '@/lib/format'
import type { DeviceCredential } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  ConnectionBadge,
  EmptyRow,
  ErrorState,
  Modal,
  PageHeader,
  Pagination,
  Select,
  TBody,
  THead,
  Table,
  Td,
  TextInput,
  Th,
  Tr,
} from '@/components/ui'

const PAGE_SIZE = 25

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

  const sites = useSites()
  const devices = useDevices({
    q: searchParams.get('q') ?? undefined,
    status: status || undefined,
    site_id: siteId || undefined,
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
          can('device:write') ? (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setShowCreate(true)}>
              {t('devices.register')}
            </Button>
          ) : null
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
            label={t('devices.site')}
            value={siteId}
            placeholder={t('common.all')}
            onChange={(event) => setParam('site', event.target.value)}
            options={(sites.data?.items ?? []).map((site) => ({
              value: site.id,
              label: site.name,
            }))}
            className="w-44"
          />
        </div>

        {devices.error ? (
          <ErrorState error={devices.error} onRetry={() => void devices.refetch()} />
        ) : (
          <>
            <Table>
              <THead>
                <Th>{t('common.status')}</Th>
                <Th>{t('devices.registeredName')}</Th>
                <Th>{t('devices.deviceId')}</Th>
                <Th>{t('devices.site')}</Th>
                <Th>{t('devices.blueprint')}</Th>
                <Th align="right">{t('devices.lastSeen')}</Th>
              </THead>
              <TBody>
                {devices.isPending ? (
                  <EmptyRow colSpan={6} message={`${t('common.loading')}…`} />
                ) : devices.data && devices.data.items.length > 0 ? (
                  devices.data.items.map((device) => (
                    <Tr key={device.id} onClick={() => navigate(`/devices/${device.id}`)}>
                      <Td>
                        <ConnectionBadge status={device.status} />
                      </Td>
                      <Td>
                        <span className="font-medium">{device.name}</span>
                        {!device.is_enabled ? (
                          <Badge tone="neutral" className="ml-2">
                            {t('common.disabled')}
                          </Badge>
                        ) : null}
                      </Td>
                      <Td className="font-mono text-xs text-muted">{device.device_id}</Td>
                      <Td className="text-muted">{device.site_name ?? '—'}</Td>
                      <Td className="text-muted">{device.device_type_name ?? '—'}</Td>
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
          <Select
            label={t('devices.site')}
            value={form.site_id}
            placeholder={t('common.none')}
            onChange={(event) => setForm({ ...form, site_id: event.target.value })}
            options={(sites.data?.items ?? []).map((site) => ({ value: site.id, label: site.name }))}
          />
          <Select
            label={t('devices.blueprint')}
            value={form.device_type_id}
            placeholder={t('common.none')}
            onChange={(event) => setForm({ ...form, device_type_id: event.target.value })}
            options={(blueprints.data ?? []).map((blueprint) => ({
              value: blueprint.id,
              label: blueprint.name,
            }))}
          />
        </div>
        <TextInput
          label={t('devices.serialNumber')}
          value={form.serial_number}
          onChange={(event) => setForm({ ...form, serial_number: event.target.value })}
        />
      </form>
    </Modal>
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
