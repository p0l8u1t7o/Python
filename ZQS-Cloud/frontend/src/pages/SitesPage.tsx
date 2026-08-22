import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import {
  Building2,
  ChevronDown,
  ChevronRight,
  Cpu,
  Factory,
  Layers,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { useDevices, useGeocode, useSiteMutations, useSites } from '@/lib/queries'
import { errorMessage, fieldErrors } from '@/lib/errors'
import type { GeocodeResult, Site, SiteKind, SiteSummary } from '@/lib/types'
import { useFormDirty } from '@/lib/useFormDirty'
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
  Select,
  SiteTreeSelect,
  TBody,
  THead,
  Table,
  Td,
  TextArea,
  TextInput,
  Th,
  TimezoneSelect,
  Tr,
} from '@/components/ui'

const KIND_ICON: Record<SiteKind, typeof Building2> = {
  site: Building2,
  area: Factory,
  line: Layers,
  group: Layers,
}

interface TreeNode {
  site: SiteSummary
  children: TreeNode[]
}

/** Nest a flat site list, keeping anything whose parent is missing at the top. */
function buildTree(sites: SiteSummary[]): TreeNode[] {
  const nodes = new Map<string, TreeNode>()
  sites.forEach((site) => nodes.set(site.id, { site, children: [] }))

  const roots: TreeNode[] = []
  nodes.forEach((node) => {
    const parent = node.site.parent_id ? nodes.get(node.site.parent_id) : undefined
    if (parent) parent.children.push(node)
    else roots.push(node)
  })
  return roots
}

function flatten(nodes: TreeNode[], collapsed: Set<string>, level = 0) {
  const rows: { node: TreeNode; level: number }[] = []
  nodes.forEach((node) => {
    rows.push({ node, level })
    if (!collapsed.has(node.site.id)) {
      rows.push(...flatten(node.children, collapsed, level + 1))
    }
  })
  return rows
}

export function SitesPage() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  // include_descendants fills total_*, so a parent row can show its subtree.
  const sites = useSites({ includeDescendants: true })
  const { remove } = useSiteMutations()
  // Devices with no site at all have nowhere to sit in a tree; surface them
  // rather than letting them quietly vanish from this page.
  const unassigned = useDevices({ unassigned_only: true, limit: 1 })

  const [editing, setEditing] = useState<SiteSummary | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<SiteSummary | null>(null)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const items = useMemo(() => sites.data?.items ?? [], [sites.data])
  const rows = useMemo(() => flatten(buildTree(items), collapsed), [items, collapsed])
  const unassignedCount = unassigned.data?.total ?? 0

  function toggle(id: string) {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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
              <Th align="right">{t('sites.devicesHere')}</Th>
              <Th align="right">{t('sites.devicesTotal')}</Th>
              <Th align="right">{t('dashboard.openAlerts')}</Th>
              <Th />
            </THead>
            <TBody>
              {sites.isPending ? (
                <EmptyRow colSpan={6} message={`${t('common.loading')}…`} />
              ) : rows.length > 0 ? (
                rows.map(({ node, level }) => {
                  const site = node.site
                  const Icon = KIND_ICON[site.kind] ?? Building2
                  const hasChildren = node.children.length > 0
                  const isCollapsed = collapsed.has(site.id)
                  return (
                    <Tr key={site.id}>
                      <Td>
                        <span
                          className="flex items-center gap-1.5"
                          style={{ paddingLeft: `${level * 1.25}rem` }}
                        >
                          {hasChildren ? (
                            <button
                              type="button"
                              onClick={() => toggle(site.id)}
                              aria-expanded={!isCollapsed}
                              aria-label={isCollapsed ? t('common.expand') : t('common.collapse')}
                              className="rounded p-0.5 text-subtle hover:text-default"
                            >
                              {isCollapsed ? (
                                <ChevronRight className="size-3.5" />
                              ) : (
                                <ChevronDown className="size-3.5" />
                              )}
                            </button>
                          ) : (
                            <span className="inline-block w-[1.125rem]" aria-hidden />
                          )}
                          <Icon className="size-3.5 shrink-0 text-subtle" aria-hidden />
                          <Link to={`/storage?site=${site.id}`} className="font-medium hover:underline">
                            {site.name}
                          </Link>
                          <span className="font-mono text-xs text-subtle">{site.code}</span>
                        </span>
                      </Td>
                      <Td className="max-w-sm truncate text-muted">{site.address || '—'}</Td>
                      <Td align="right" className="tnum">
                        <Badge tone={site.online_count === site.device_count ? 'ok' : 'neutral'}>
                          {site.online_count}/{site.device_count}
                        </Badge>
                      </Td>
                      <Td align="right" className="tnum">
                        {hasChildren ? (
                          <span className="text-muted">
                            {site.total_online_count}/{site.total_device_count}
                          </span>
                        ) : (
                          <span className="text-subtle">—</span>
                        )}
                      </Td>
                      <Td align="right">
                        {site.total_open_alert_count > 0 ? (
                          <Badge tone="critical">{site.total_open_alert_count}</Badge>
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
                  )
                })
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

              {unassignedCount > 0 ? (
                <Tr key="__unassigned">
                  <Td>
                    <span className="flex items-center gap-1.5">
                      <span className="inline-block w-[1.125rem]" aria-hidden />
                      <Cpu className="size-3.5 shrink-0 text-subtle" aria-hidden />
                      <Link to="/devices?unassigned=1" className="font-medium italic hover:underline">
                        {t('sites.unassigned')}
                      </Link>
                    </span>
                  </Td>
                  <Td className="text-subtle">{t('sites.unassignedHint')}</Td>
                  <Td align="right" className="tnum">
                    <Badge tone="warning">{unassignedCount}</Badge>
                  </Td>
                  <Td align="right" className="text-subtle">
                    —
                  </Td>
                  <Td align="right" className="text-subtle">
                    —
                  </Td>
                  <Td />
                </Tr>
              ) : null}
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
  parent_id: '',
  kind: 'site' as SiteKind,
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
  const sites = useSites()
  const [form, setForm] = useState(EMPTY)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const dirty = useFormDirty(open, form)

  // Geocoding is a convenience, never a requirement: every failure path here
  // ends with the operator typing the numbers in, which is why nothing below
  // surfaces an error state.
  const geocode = useGeocode()
  const [matches, setMatches] = useState<GeocodeResult[]>([])
  const [geocodeNote, setGeocodeNote] = useState('')

  async function lookup() {
    setGeocodeNote('')
    setMatches([])
    try {
      const response = await geocode.mutateAsync(form.address.trim())
      if (!response.available) {
        setGeocodeNote(t('sites.geocodeUnavailable'))
        return
      }
      if (response.results.length === 0) {
        setGeocodeNote(t('sites.geocodeNoMatch'))
        return
      }
      setMatches(response.results)
    } catch {
      setGeocodeNote(t('sites.geocodeFailed'))
    }
  }

  // A site may not become its own descendant, so its own subtree cannot appear
  // in the parent picker. The server rejects it too; filtering here just keeps
  // the operator from picking an option that can only fail.
  const parentOptions = useMemo(() => {
    const all = sites.data?.items ?? []
    const banned = new Set<string>()
    if (site) {
      banned.add(site.id)
      let grew = true
      while (grew) {
        grew = false
        all.forEach((candidate) => {
          if (candidate.parent_id && banned.has(candidate.parent_id) && !banned.has(candidate.id)) {
            banned.add(candidate.id)
            grew = true
          }
        })
      }
    }
    return all.filter((candidate) => !banned.has(candidate.id))
  }, [sites.data, site])

  useEffect(() => {
    if (!open) return
    setErrors({})
    setForm(
      site
        ? {
            name: site.name,
            code: site.code,
            parent_id: site.parent_id ?? '',
            kind: site.kind,
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
  }, [open, site?.id])

  async function submit() {
    setErrors({})
    const payload = {
      name: form.name.trim(),
      // An empty select means "top level"; send null, not "".
      parent_id: form.parent_id === '' ? null : form.parent_id,
      kind: form.kind,
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
      dirty={dirty}
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
        <SiteTreeSelect
          label={t('sites.parent')}
          sites={parentOptions}
          value={form.parent_id}
          error={errors.parent_id}
          placeholder={t('sites.topLevel')}
          allowClear
          hint={t('sites.parentHint')}
          onChange={(value) => setForm({ ...form, parent_id: value })}
        />
        <Select
          label={t('sites.kind')}
          value={form.kind}
          options={(['site', 'area', 'line', 'group'] as SiteKind[]).map((kind) => ({
            value: kind,
            label: t(`sites.kinds.${kind}`),
          }))}
          onChange={(event) => setForm({ ...form, kind: event.target.value as SiteKind })}
        />
        <div className="sm:col-span-2 space-y-2">
          <div className="flex items-end gap-2">
            <TextInput
              label={t('sites.address')}
              className="flex-1"
              value={form.address}
              onChange={(event) => setForm({ ...form, address: event.target.value })}
            />
            <Button
              onClick={() => void lookup()}
              loading={geocode.isPending}
              disabled={form.address.trim().length < 3}
            >
              {t('sites.findCoordinates')}
            </Button>
          </div>
          {geocodeNote ? <p className="text-xs text-muted">{geocodeNote}</p> : null}
          {matches.length > 0 ? (
            <ul className="divide-y divide-line rounded border border-line">
              {matches.map((match) => (
                <li key={`${match.latitude},${match.longitude}`}>
                  <button
                    type="button"
                    className="w-full px-3 py-2 text-left text-xs hover:bg-subtle"
                    onClick={() => {
                      setForm((current) => ({
                        ...current,
                        latitude: String(match.latitude),
                        longitude: String(match.longitude),
                        // Only overwrite what the lookup actually resolved.
                        // A blank city from the geocoder must not wipe one the
                        // operator already typed.
                        city: match.city || current.city,
                        country: match.country || current.country,
                        timezone_name: match.timezone_name || current.timezone_name,
                      }))
                      setMatches([])
                      setGeocodeNote(t('sites.coordinatesFilled'))
                    }}
                  >
                    <span className="block">{match.display_name}</span>
                    <span className="block font-mono text-muted">
                      {match.latitude.toFixed(5)}, {match.longitude.toFixed(5)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
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
        <TimezoneSelect
          label={t('sites.timezone')}
          value={form.timezone_name}
          error={errors.timezone_name}
          onChange={(zone) => setForm({ ...form, timezone_name: zone })}
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
