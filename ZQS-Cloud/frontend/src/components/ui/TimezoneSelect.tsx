import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { useTimezones } from '../../lib/queries'
import { Select, TextInput } from './Field'

/**
 * Current UTC offset for a zone, e.g. `UTC+8`.
 *
 * Computed rather than tabulated because offsets move: half the world changes
 * twice a year, and a hard-coded table is wrong for six months at a time.
 * Returns an empty string for a zone this browser cannot resolve, so an
 * unfamiliar name degrades to a bare label instead of throwing inside render.
 */
function offsetOf(zone: string): string {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      timeZoneName: 'shortOffset',
    }).formatToParts(new Date())
    return parts.find((part) => part.type === 'timeZoneName')?.value ?? ''
  } catch {
    return ''
  }
}

interface Props {
  label?: React.ReactNode
  value: string
  onChange: (zone: string) => void
  hint?: React.ReactNode
  error?: string
  required?: boolean
  className?: string
}

/**
 * Pick an IANA timezone from what the server can actually resolve.
 *
 * Two decisions worth stating:
 *
 * - **The list comes from the API, not from a constant here.** The value has
 *   to survive server-side validation, so the only list worth offering is the
 *   one the server will accept.
 * - **Grouped by region, with the current offset shown.** Five hundred flat
 *   names is a scroll, not a choice; `Asia/Taipei (UTC+8)` under an `Asia`
 *   heading is findable.
 *
 * Falls back to a free-text field while the list is loading or if it fails to
 * load. A dropdown that has not arrived must not stop someone saving a site.
 */
export function TimezoneSelect({
  label,
  value,
  onChange,
  hint,
  error,
  required,
  className,
}: Props) {
  const { t } = useTranslation()
  const zones = useTimezones()

  const grouped = useMemo(() => {
    const list = zones.data ?? []
    const groups = new Map<string, { value: string; label: string }[]>()
    for (const zone of list) {
      const slash = zone.indexOf('/')
      // `UTC` has no region prefix. Naming its own group after itself reads
      // better than filing it under "Other", where nobody would look for it.
      const area = slash === -1 ? zone : zone.slice(0, slash)
      const city = slash === -1 ? zone : zone.slice(slash + 1).replace(/_/g, ' ')
      const offset = offsetOf(zone)
      const entry = {
        value: zone,
        label: offset ? `${area} — ${city} (${offset})` : `${area} — ${city}`,
      }
      const bucket = groups.get(area)
      if (bucket) bucket.push(entry)
      else groups.set(area, [entry])
    }
    return [...groups.entries()]
  }, [zones.data])

  if (zones.isPending || zones.isError || grouped.length === 0) {
    return (
      <TextInput
        label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        hint={hint ?? t('common.timezoneManualHint')}
        error={error}
        required={required}
        className={className}
      />
    )
  }

  // The stored value may be a zone the server no longer offers - a tzdata
  // update retires names. Showing it keeps an existing record editable
  // instead of silently rewriting it to whatever happens to be first.
  const known = grouped.some(([, entries]) => entries.some((e) => e.value === value))

  return (
    <Select
      label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      hint={hint}
      error={error}
      required={required}
      className={className}
      options={[
        ...(known || !value ? [] : [{ value, label: `${value} (${t('common.unknown')})` }]),
        ...grouped.flatMap(([, entries]) => entries),
      ]}
    />
  )
}
