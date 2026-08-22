import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import {
  BatteryCharging,
  Cable,
  Cpu,
  Fuel,
  Gauge,
  HardDrive,
  Lightbulb,
  Plug,
  Router,
  Sun,
  Thermometer,
  Zap,
} from 'lucide-react'

/**
 * One icon per device category.
 *
 * The category - not the blueprint, not the name - because it is the thing the
 * platform actually reasons about, and it is fixed for a device's whole life:
 * a device's category never changes, so its icon never changes either, and a
 * row does not quietly become a different shape after an edit.
 *
 * Distinct silhouettes matter more than literal ones at 16px. A meter and a
 * sensor both measure, but a dial and a thermometer are told apart instantly;
 * two variations on "gauge" would not be.
 */
export const CATEGORY_ICON = {
  battery: BatteryCharging,
  pcs: Zap,
  generation: Sun,
  meter: Gauge,
  load: Lightbulb,
  generator: Fuel,
  ev_charger: Plug,
  controller: Cpu,
  sensor: Thermometer,
  gateway: Router,
  other: HardDrive,
} as const

export type DeviceCategoryKey = keyof typeof CATEGORY_ICON

/**
 * Accent per category, kept deliberately coarse.
 *
 * Colour carries meaning elsewhere in the console - green is online, red is an
 * alert - so category colour must not compete with it. These are muted enough
 * to read as "what kind of thing" rather than "how is it doing", and the
 * status badge stays the only thing that shouts.
 */
const CATEGORY_TONE: Record<string, string> = {
  battery: 'text-brand',
  pcs: 'text-brand',
  generation: 'text-warning',
  meter: 'text-info',
  load: 'text-muted',
  generator: 'text-major',
  ev_charger: 'text-info',
  controller: 'text-muted',
  sensor: 'text-muted',
  gateway: 'text-muted',
  other: 'text-subtle',
}

function iconFor(category: string) {
  return CATEGORY_ICON[category as DeviceCategoryKey] ?? Cable
}

/**
 * The icon for a device category, with its name as the accessible label.
 *
 * An unrecognised category - a tenant blueprint from a newer server, a device
 * with no blueprint at all - falls through to a neutral glyph rather than
 * rendering nothing, so the column never jumps about.
 */
export function DeviceIcon({
  category,
  className = 'size-4',
  withTone = true,
  title,
}: {
  category: string
  className?: string
  withTone?: boolean
  title?: string
}) {
  const { t } = useTranslation()
  const Icon = iconFor(category)
  const label =
    title ??
    (category
      ? t(`devices.categories.${category}`, { defaultValue: category })
      : t('devices.noCategory'))

  // Labelled with aria-label rather than a <title> child: lucide splices
  // children into the SVG's element array, and a keyless child there produces
  // a React list-key warning on every render.
  return (
    <Icon
      className={`${className} ${withTone ? CATEGORY_TONE[category] ?? 'text-subtle' : ''}`}
      role="img"
      aria-label={label}
    />
  )
}

/** The icon in a tinted square - for page headers and cards. */
export function DeviceIconBadge({
  category,
  className = '',
}: {
  category: string
  className?: string
}): ReactNode {
  return (
    <span
      className={`grid size-8 shrink-0 place-items-center rounded-lg bg-surface-muted ${className}`}
    >
      <DeviceIcon category={category} className="size-4" />
    </span>
  )
}
