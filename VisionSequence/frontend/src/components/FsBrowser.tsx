/** 伺服器檔案瀏覽器（來源設定選資料夾／影像檔）：GET /vision/fs 逐層瀏覽。
 *  路徑是「執行後端那台機器」上的路徑——一體機（前後端同機）就是本機檔案。 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowUp, FileImage, Folder, Loader2 } from 'lucide-react'

import { Button, Modal, TextInput } from '@/components/ui'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/errors'

interface FsListing {
  path: string
  parent: string | null
  dirs: string[]
  files: string[]
}

export function FsBrowser({ open, onClose, mode, initial, onPick }: {
  open: boolean
  onClose: () => void
  /** dir＝選資料夾（folder 來源）、file＝選影像檔（file 來源） */
  mode: 'dir' | 'file'
  initial?: string
  onPick: (path: string) => void
}) {
  const { t } = useTranslation()
  const [path, setPath] = useState('')
  const [input, setInput] = useState('')
  const [data, setData] = useState<FsListing | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) {
      const start = (initial || '').trim()
      setPath(start)
      setInput(start)
    }
  }, [open, initial])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError('')
    api.get<FsListing>('/vision/fs', { path })
      .then((r) => {
        if (!cancelled) {
          setData(r)
          setInput(r.path)
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(errorMessage(e))
          setData(null)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, path])

  const join = (name: string) => (data?.path ? `${data.path.replace(/[\\/]+$/, '')}\\${name}` : name)

  return (
    <Modal open={open} onClose={onClose} title={mode === 'dir' ? t('fs.pickDir') : t('fs.pickFile')} description={t('fs.serverHint')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          {mode === 'dir' ? (
            <Button variant="primary" disabled={!data?.path} onClick={() => { if (data?.path) { onPick(data.path); onClose() } }} data-testid="fs-pick-dir">
              {t('fs.useThisDir')}
            </Button>
          ) : null}
        </>
      }>
      <div className="space-y-3">
        <div className="flex items-end gap-2">
          <TextInput label={t('fs.path')} value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') setPath(input.trim()) }} className="font-mono" data-testid="fs-path" />
          <Button onClick={() => setPath(input.trim())}>{t('fs.go')}</Button>
          <Button disabled={data?.parent === null || data?.parent === undefined} title={t('fs.up')}
            onClick={() => setPath(data?.parent ?? '')}><ArrowUp size={14} /></Button>
        </div>
        {error ? <p className="rounded-md bg-critical-soft px-3 py-2 text-xs text-critical">{error}</p> : null}
        <div className="max-h-[46vh] space-y-0.5 overflow-y-auto rounded-lg border border-line p-1.5" data-testid="fs-listing">
          {loading ? <p className="flex items-center gap-2 px-2 py-3 text-xs text-muted"><Loader2 size={13} className="animate-spin" /> {t('common.loading')}</p> : null}
          {!loading && data ? (
            <>
              {data.dirs.map((name) => (
                <button key={`d-${name}`} type="button" onClick={() => setPath(data.path ? join(name) : name)}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-muted">
                  <Folder size={15} className="shrink-0 text-warning" aria-hidden />
                  <span className="truncate font-mono text-xs">{name}</span>
                </button>
              ))}
              {mode === 'file' ? data.files.map((name) => (
                <button key={`f-${name}`} type="button" onClick={() => { onPick(join(name)); onClose() }}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-brand-soft" data-testid="fs-file">
                  <FileImage size={15} className="shrink-0 text-info" aria-hidden />
                  <span className="truncate font-mono text-xs">{name}</span>
                </button>
              )) : null}
              {!data.dirs.length && (mode === 'dir' || !data.files.length) ? <p className="px-2 py-2 text-xs text-subtle">{t('fs.empty')}</p> : null}
            </>
          ) : null}
        </div>
      </div>
    </Modal>
  )
}
