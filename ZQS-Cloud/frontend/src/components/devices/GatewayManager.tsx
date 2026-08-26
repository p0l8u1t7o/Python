import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound, Plus, RefreshCw, Trash2 } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { useEdgeNodeMutations, useEdgeNodes, useSites } from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import { formatRelative } from '@/lib/format'
import { useFormDirty } from '@/lib/useFormDirty'
import type { DeviceCredential, EdgeNode } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  EmptyRow,
  IconButton,
  Modal,
  ConnectionBadge,
  Select,
  Table,
  TBody,
  Td,
  TextInput,
  Th,
  THead,
  Tr,
} from '@/components/ui'
import { CredentialPanel } from '@/pages/DevicesPage'

/**
 * The gateways (Sparkplug edge nodes) of this tenant, with the four things an
 * operator needs to do to one: register it ahead of the vendor arriving, hand
 * over (or rotate) its MQTT credential, ask it to re-announce itself when
 * the platform and the gateway disagree about what is attached, and remove
 * it. The API has had all four for a while; the console only listed them.
 */
export function GatewayManager({
  selectedId = null,
  onSelect,
}: {
  /** Highlighted row; the page shows this gateway's detail below. */
  selectedId?: string | null
  onSelect?: (id: string) => void
} = {}) {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const nodes = useEdgeNodes({ include_implicit: false })
  const { create, remove, rotate, rebirth } = useEdgeNodeMutations()
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<EdgeNode | null>(null)
  const [rotating, setRotating] = useState<EdgeNode | null>(null)
  const [credential, setCredential] = useState<{ node: string; credential: DeviceCredential } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  async function requestRebirth(node: EdgeNode) {
    setBusy(node.id)
    try {
      await rebirth.mutateAsync(node.id)
      toast.success(t('gateways.rebirthSent', { node: node.node_id }))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusy(null)
    }
  }

  async function confirmRotate() {
    if (!rotating) return
    try {
      const result = await rotate.mutateAsync(rotating.id)
      setCredential({ node: rotating.node_id, credential: result })
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setRotating(null)
    }
  }

  async function confirmDelete() {
    if (!deleting) return
    try {
      await remove.mutateAsync(deleting.id)
      toast.success(t('gateways.deleted'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setDeleting(null)
    }
  }

  const items = nodes.data?.items ?? []
  const writable = can('device:write')

  return (
    <Card>
      <CardHeader
        title={t('gateways.title')}
        description={onSelect ? `${t('gateways.hint')} ${t('gateways.selectHint')}` : t('gateways.hint')}
        actions={
          writable ? (
            <Button icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
              {t('gateways.create')}
            </Button>
          ) : undefined
        }
      />
      <Table>
        <THead>
          <Th>{t('gateways.nodeId')}</Th>
          <Th>{t('common.name')}</Th>
          <Th>{t('common.status')}</Th>
          <Th>{t('gateways.lastSeen')}</Th>
          <Th align="right">{t('gateways.devices')}</Th>
          {writable ? <Th /> : null}
        </THead>
        <TBody>
          {items.length === 0 ? (
            <EmptyRow colSpan={6} message={t('gateways.empty')} />
          ) : (
            items.map((node) => (
              <Tr
                key={node.id}
                onClick={onSelect ? () => onSelect(node.id) : undefined}
                className={node.id === selectedId ? 'bg-brand-soft/40' : ''}
              >
                <Td className="font-mono text-xs">{node.node_id}</Td>
                <Td>
                  <span className="font-medium">{node.name}</span>
                  {!node.is_enabled ? <Badge tone="neutral" className="ml-1">{t('common.disabled')}</Badge> : null}
                </Td>
                <Td>
                  <ConnectionBadge status={node.status} />
                  {node.rebirth_requested_at ? (
                    <span className="ml-1 text-xs text-muted">{t('gateways.rebirthPending')}</span>
                  ) : null}
                </Td>
                <Td className="text-muted">{node.last_seen_at ? formatRelative(node.last_seen_at) : '—'}</Td>
                <Td align="right" className="tnum">{node.device_count}</Td>
                {writable ? (
                  <Td align="right">
                    <span className="flex justify-end gap-1" onClick={(event) => event.stopPropagation()}>
                      <IconButton
                        label={t('gateways.rebirth')}
                        onClick={() => void requestRebirth(node)}
                        disabled={busy === node.id}
                      >
                        <RefreshCw className="size-3.5" />
                      </IconButton>
                      <IconButton label={t('gateways.rotate')} onClick={() => setRotating(node)}>
                        <KeyRound className="size-3.5" />
                      </IconButton>
                      <IconButton label={t('common.delete')} onClick={() => setDeleting(node)}>
                        <Trash2 className="size-3.5" />
                      </IconButton>
                    </span>
                  </Td>
                ) : null}
              </Tr>
            ))
          )}
        </TBody>
      </Table>

      <CreateGatewayModal
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(nodeId, cred) => {
          setCreating(false)
          if (cred) setCredential({ node: nodeId, credential: cred })
        }}
        create={create}
      />

      <ConfirmDialog
        open={rotating !== null}
        onClose={() => setRotating(null)}
        onConfirm={() => void confirmRotate()}
        title={t('gateways.rotate')}
        danger
        loading={rotate.isPending}
        message={t('gateways.rotateConfirm', { node: rotating?.node_id ?? '' })}
      />
      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => void confirmDelete()}
        title={t('common.delete')}
        danger
        loading={remove.isPending}
        message={t('gateways.deleteConfirm', { node: deleting?.node_id ?? '' })}
      />
      <Modal
        open={credential !== null}
        onClose={() => setCredential(null)}
        title={t('gateways.credentialTitle', { node: credential?.node ?? '' })}
        description={t('gateways.credentialHint')}
        footer={<Button variant="primary" onClick={() => setCredential(null)}>{t('common.close')}</Button>}
      >
        {credential ? <CredentialPanel credential={credential.credential} /> : null}
      </Modal>
    </Card>
  )
}

function CreateGatewayModal({
  open,
  onClose,
  onCreated,
  create,
}: {
  open: boolean
  onClose: () => void
  onCreated: (nodeId: string, credential: DeviceCredential | null) => void
  create: ReturnType<typeof useEdgeNodeMutations>['create']
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const sites = useSites()
  const [form, setForm] = useState({ node_id: '', name: '', description: '', site_id: '', is_enabled: true })
  const dirty = useFormDirty(open, form)
  const idProblem =
    form.node_id && !/^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$/.test(form.node_id)
      ? t('gateways.nodeIdInvalid')
      : undefined

  async function submit() {
    try {
      const result = await create.mutateAsync({
        node_id: form.node_id.trim(),
        name: form.name.trim(),
        description: form.description,
        site_id: form.site_id || null,
        is_enabled: form.is_enabled,
      })
      toast.success(t('common.saved'))
      setForm({ node_id: '', name: '', description: '', site_id: '', is_enabled: true })
      onCreated(result.edge_node.node_id, result.credential)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      dirty={dirty}
      title={t('gateways.create')}
      description={t('gateways.createHint')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            disabled={!form.node_id.trim() || Boolean(idProblem)}
            loading={create.isPending}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextInput
          label={t('gateways.nodeId')}
          required
          value={form.node_id}
          placeholder="GW-PLANT-01"
          error={idProblem}
          hint={t('gateways.nodeIdHint')}
          onChange={(event) => setForm({ ...form, node_id: event.target.value })}
        />
        <TextInput
          label={t('common.name')}
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />
        <Select
          label={t('gateways.site')}
          value={form.site_id}
          placeholder={t('common.none')}
          options={(sites.data?.items ?? []).map((site) => ({ value: site.id, label: site.name }))}
          onChange={(event) => setForm({ ...form, site_id: event.target.value })}
        />
        <Checkbox
          label={t('common.enabled')}
          checked={form.is_enabled}
          onChange={(is_enabled) => setForm({ ...form, is_enabled })}
        />
      </div>
    </Modal>
  )
}
