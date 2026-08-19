import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Building2, Pencil, Plus, Trash2 } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { useSiteMutations, useSites } from '@/lib/queries'
import { errorMessage, fieldErrors } from '@/lib/errors'
import type { Site, SiteSummary } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyRow,
  ErrorState,
  IconButton,
  Modal,
  PageHeader,
  TBody,
  THead,
  Table,
  Td,
  TextArea,
  TextInput,
  Th,
  Tr,
} from '@/components/ui'

export function SitesPage() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const sites = useSites()
  const { remove } = useSiteMutations()

  const [editing, setEditing] = useState<SiteSummary | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<SiteSummary | null>(null)

  return (
    <>
      <PageHeader
        title={t('sites.title')}
        description={t('sites.subtitle')}
        actions={
          can('site:write') ? (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
              {t('sites.create')}
            </Button>
          ) : null
        }
      />

      <Card>
        {sites.error ? (
          <ErrorState error={sites.error} onRetry={() => void sites.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('sites.site')}</Th>
              <Th>{t('sites.address')}</Th>
              <Th>{t('sites.coordinates')}</Th>
              <Th align="right">{t('sites.devices')}</Th>
              <Th align="right">{t('dashboard.openAlerts')}</Th>
              <Th />
            </THead>
            <TBody>
              {sites.isPending ? (
                <EmptyRow colSpan={6} message={`${t('common.loading')}…`} />
              ) : sites.data && sites.data.items.length > 0 ? (
                sites.data.items.map((site) => (
                  <Tr key={site.id}>
                    <Td>
                      <Link to={`/storage?site=${site.id}`} className="font-medium hover:underline">
                        {site.name}
                      </Link>
                      <span className="ml-1.5 font-mono text-xs text-subtle">{site.code}</span>
                    </Td>
                    <Td className="max-w-sm truncate text-muted">{site.address || '—'}</Td>
                    <Td className="tnum text-muted">
                      {site.latitude !== null && site.longitude !== null
                        ? `${site.latitude.toFixed(4)}, ${site.longitude.toFixed(4)}`
                        : '—'}
                    </Td>
                    <Td align="right" className="tnum">
                      <Badge tone={site.online_count === site.device_count ? 'ok' : 'neutral'}>
                        {site.online_count}/{site.device_count}
                      </Badge>
                    </Td>
                    <Td align="right">
                      {site.open_alert_count > 0 ? (
                        <Badge tone="critical">{site.open_alert_count}</Badge>
                      ) : (
                        <span className="text-subtle">—</span>
                      )}
                    </Td>
                    <Td align="right">
                      {can('site:write') ? (
                        <span className="flex justify-end gap-1">
                          <IconButton label={t('common.edit')} onClick={() => setEditing(site)}>
                            <Pencil className="size-3.5" />
                          </IconButton>
                          <IconButton label={t('common.delete')} onClick={() => setDeleting(site)}>
                            <Trash2 className="size-3.5" />
                          </IconButton>
                        </span>
                      ) : null}
                    </Td>
                  </Tr>
                ))
              ) : (
                <EmptyRow
                  colSpan={6}
                  message={
                    <span className="flex flex-col items-center gap-2">
                      <Building2 className="size-6 text-subtle" aria-hidden />
                      {t('sites.noSites')}
                    </span>
                  }
                />
              )}
            </TBody>
          </Table>
        )}
      </Card>

      <SiteModal
        open={creating || editing !== null}
        site={editing}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
      />

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        danger
        loading={remove.isPending}
        title={t('common.delete')}
        confirmLabel={t('common.delete')}
        message={t('sites.deleteConfirm', { name: deleting?.name ?? '' })}
        onConfirm={async () => {
          if (!deleting) return
          try {
            await remove.mutateAsync(deleting.id)
            setDeleting(null)
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />
    </>
  )
}

const EMPTY = {
  name: '',
  code: '',
  description: '',
  address: '',
  city: '',
  country: '',
  latitude: '',
  longitude: '',
  timezone_name: 'Asia/Taipei',
  contact_name: '',
  contact_phone: '',
}

function SiteModal({
  open,
  site,
  onClose,
}: {
  open: boolean
  site: Site | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const { create, update } = useSiteMutations()
  const [form, setForm] = useState(EMPTY)
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!open) return
    setErrors({})
    setForm(
      site
        ? {
            name: site.name,
            code: site.code,
            description: site.description,
            address: site.address,
            city: site.city,
            country: site.country,
            latitude: site.latitude?.toString() ?? '',
            longitude: site.longitude?.toString() ?? '',
            timezone_name: site.timezone_name,
            contact_name: site.contact_name,
            contact_phone: site.contact_phone,
          }
        : EMPTY,
    )
  }, [open, site])

  async function submit() {
    setErrors({})
    const payload = {
      name: form.name.trim(),
      description: form.description,
      address: form.address,
      city: form.city,
      country: form.country.toUpperCase(),
      latitude: form.latitude === '' ? null : Number(form.latitude),
      longitude: form.longitude === '' ? null : Number(form.longitude),
      timezone_name: form.timezone_name,
      contact_name: form.contact_name,
      contact_phone: form.contact_phone,
    }
    try {
      if (site) {
        await update.mutateAsync({ id: site.id, ...payload })
      } else {
        await create.mutateAsync({ ...payload, code: form.code.trim() })
      }
      toast.success(t('common.saved'))
      onClose()
    } catch (error) {
      setErrors(fieldErrors(error))
      toast.error(errorMessage(error))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={site ? t('sites.edit') : t('sites.create')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={create.isPending || update.isPending}
            disabled={!form.name || (!site && !form.code)}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <TextInput
          label={t('common.name')}
          required
          value={form.name}
          error={errors.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />
        <TextInput
          label={t('sites.code')}
          required={!site}
          disabled={Boolean(site)}
          value={form.code}
          error={errors.code}
          onChange={(event) => setForm({ ...form, code: event.target.value })}
          placeholder="taipei-hq"
          hint={site ? undefined : 'lowercase-with-dashes'}
          className="font-mono"
        />
        <TextInput
          label={t('sites.address')}
          className="sm:col-span-2"
          value={form.address}
          onChange={(event) => setForm({ ...form, address: event.target.value })}
        />
        <TextInput
          label={t('sites.city')}
          value={form.city}
          onChange={(event) => setForm({ ...form, city: event.target.value })}
        />
        <TextInput
          label={t('sites.country')}
          maxLength={2}
          value={form.country}
          onChange={(event) => setForm({ ...form, country: event.target.value })}
          placeholder="TW"
          hint="ISO 3166-1 alpha-2"
        />
        <TextInput
          label={t('sites.latitude')}
          type="number"
          step="any"
          min={-90}
          max={90}
          value={form.latitude}
          error={errors.latitude}
          onChange={(event) => setForm({ ...form, latitude: event.target.value })}
        />
        <TextInput
          label={t('sites.longitude')}
          type="number"
          step="any"
          min={-180}
          max={180}
          value={form.longitude}
          error={errors.longitude}
          onChange={(event) => setForm({ ...form, longitude: event.target.value })}
        />
        <TextInput
          label={t('sites.timezone')}
          value={form.timezone_name}
          error={errors.timezone_name}
          onChange={(event) => setForm({ ...form, timezone_name: event.target.value })}
          placeholder="Asia/Taipei"
        />
        <TextInput
          label={t('sites.contact')}
          value={form.contact_name}
          onChange={(event) => setForm({ ...form, contact_name: event.target.value })}
        />
        <TextArea
          label={t('common.description')}
          className="sm:col-span-2"
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
        />
      </div>
    </Modal>
  )
}
