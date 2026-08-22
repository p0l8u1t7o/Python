import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import {
  Activity,
  BatteryCharging,
  Bell,
  BookOpen,
  Building2,
  ChevronDown,
  ChevronRight,
  Cpu,
  ExternalLink,
  LayoutDashboard,
  Map as MapIcon,
  Receipt,
  Rocket,
  Search,
  Settings,
  SlidersHorizontal,
} from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useCapabilities } from '@/lib/queries'
import { CATEGORY_ICON } from '@/components/ui/DeviceIcon'
import { GLOSSARY, type GlossaryEntry, type GlossaryId } from '@/lib/glossary'
import { currentLanguage } from '@/i18n'
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  DeviceIcon,
  EmptyState,
  PageHeader,
  TextInput,
} from '@/components/ui'

/**
 * Getting started, page by page, plus the vocabulary.
 *
 * Deliberately not a link to external documentation: the questions this
 * answers - "what do I do first", "what is a blueprint" - arrive while
 * somebody is looking at the console, and sending them to another tab is how
 * they end up guessing instead.
 *
 * The glossary section reuses `GLOSSARY`, the same source the term bubbles
 * read. One definition, two places it appears; a second copy would drift.
 */
export function HelpPage() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')

  return (
    <>
      <PageHeader title={t('help.title')} description={t('help.subtitle')} />

      <div className="mb-5">
        <TextInput
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t('help.searchPlaceholder')}
          className="pl-3"
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <FirstStepsCard query={query} />
          <PageGuideCard query={query} />
          <DeviceTypesCard query={query} />
          <GlossaryCard query={query} />
        </div>

        <div className="space-y-5">
          <TroubleshootingCard query={query} />
          <EnvironmentCard />
        </div>
      </div>
    </>
  )
}

/** Case-insensitive substring match across a few fields. */
function matches(query: string, ...fields: (string | undefined)[]): boolean {
  const needle = query.trim().toLowerCase()
  if (!needle) return true
  return fields.some((field) => field?.toLowerCase().includes(needle))
}

// ---------------------------------------------------------------------------
function FirstStepsCard({ query }: { query: string }) {
  const { t } = useTranslation()
  const { can } = useAuth()

  /**
   * The order matters and is not arbitrary - each step is unusable before the
   * one above it. A device with no site cannot appear on the map; an energy
   * balance with no asset bindings has nothing to add up.
   */
  const steps: {
    key: string
    to: string
    icon: typeof Building2
    permission?: string
  }[] = [
    { key: 'site', to: '/sites', icon: Building2, permission: 'site:write' },
    { key: 'device', to: '/devices', icon: Cpu, permission: 'device:write' },
    { key: 'asset', to: '/storage', icon: BatteryCharging, permission: 'ems:write' },
    { key: 'tariff', to: '/tariffs', icon: Receipt, permission: 'ems:write' },
    { key: 'rules', to: '/rules', icon: Bell, permission: 'alert:rule:write' },
    { key: 'watch', to: '/', icon: LayoutDashboard },
  ]

  const visible = steps.filter((step) =>
    matches(query, t(`help.steps.${step.key}.title`), t(`help.steps.${step.key}.body`)),
  )
  if (visible.length === 0) return null

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Rocket className="size-4 text-brand" aria-hidden />
            {t('help.firstSteps')}
          </span>
        }
        description={t('help.firstStepsHint')}
      />
      <CardBody>
        <ol className="space-y-4">
          {visible.map((step, index) => {
            const allowed = !step.permission || can(step.permission)
            return (
              <li key={step.key} className="flex gap-3">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-semibold text-brand">
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    <step.icon className="size-4 text-subtle" aria-hidden />
                    {t(`help.steps.${step.key}.title`)}
                    {!allowed ? (
                      <Badge tone="neutral">{t('help.needsPermission')}</Badge>
                    ) : null}
                  </p>
                  <p className="mt-1 text-sm text-muted">
                    {t(`help.steps.${step.key}.body`)}
                  </p>
                  {allowed ? (
                    <Link
                      to={step.to}
                      className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
                    >
                      {t('help.goThere')}
                      <ChevronRight className="size-3" aria-hidden />
                    </Link>
                  ) : null}
                </div>
              </li>
            )
          })}
        </ol>
      </CardBody>
    </Card>
  )
}

// ---------------------------------------------------------------------------
const PAGES: { key: string; to: string; icon: typeof LayoutDashboard }[] = [
  { key: 'dashboard', to: '/', icon: LayoutDashboard },
  { key: 'devices', to: '/devices', icon: Cpu },
  { key: 'map', to: '/map', icon: MapIcon },
  { key: 'alerts', to: '/alerts', icon: Bell },
  { key: 'storage', to: '/storage', icon: BatteryCharging },
  { key: 'telemetry', to: '/telemetry', icon: Activity },
  { key: 'tariffs', to: '/tariffs', icon: Receipt },
  { key: 'sites', to: '/sites', icon: Building2 },
  { key: 'recording', to: '/recording', icon: SlidersHorizontal },
  { key: 'settings', to: '/settings', icon: Settings },
]

function PageGuideCard({ query }: { query: string }) {
  const { t } = useTranslation()

  const visible = PAGES.filter((page) =>
    matches(query, t(`help.pages.${page.key}.title`), t(`help.pages.${page.key}.body`)),
  )
  if (visible.length === 0) return null

  return (
    <Card>
      <CardHeader title={t('help.pageGuide')} description={t('help.pageGuideHint')} />
      <div className="divide-y divide-line">
        {visible.map((page) => (
          <Link
            key={page.key}
            to={page.to}
            className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-surface-muted/60"
          >
            <page.icon className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
            <span className="min-w-0">
              <span className="block text-sm font-medium">
                {t(`help.pages.${page.key}.title`)}
              </span>
              <span className="block text-sm text-muted">
                {t(`help.pages.${page.key}.body`)}
              </span>
            </span>
          </Link>
        ))}
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
/**
 * What each device category means.
 *
 * Here as well as in the registration form because the choice is effectively
 * permanent: a device's category never changes, so getting it wrong means
 * registering a replacement rather than editing a field.
 */
function DeviceTypesCard({ query }: { query: string }) {
  const { t } = useTranslation()
  const categories = Object.keys(CATEGORY_ICON)

  const visible = categories.filter((category) =>
    matches(
      query,
      t(`devices.categories.${category}`),
      t(`devices.categoryHelp.${category}`, { defaultValue: '' }),
      category,
    ),
  )
  if (visible.length === 0) return null

  return (
    <Card>
      <CardHeader
        title={t('help.deviceTypes')}
        description={t('help.deviceTypesHint')}
      />
      <div className="grid gap-px bg-line sm:grid-cols-2">
        {visible.map((category) => (
          <div key={category} className="bg-surface p-3.5">
            <p className="flex items-center gap-2 text-sm font-medium">
              <DeviceIcon category={category} />
              {t(`devices.categories.${category}`, { defaultValue: category })}
            </p>
            <p className="mt-1 text-xs text-muted">
              {t(`devices.categoryHelp.${category}`, { defaultValue: '' })}
            </p>
          </div>
        ))}
      </div>
      <CardBody className="border-t border-line">
        <p className="text-xs text-subtle">{t('devices.categoryImmutable')}</p>
      </CardBody>
    </Card>
  )
}

// ---------------------------------------------------------------------------
function GlossaryCard({ query }: { query: string }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const language = currentLanguage()

  const entries = useMemo(() => {
    const ids = Object.keys(GLOSSARY) as GlossaryId[]
    return ids
      .map((id) => {
        // GLOSSARY is a const object, so TypeScript narrows each entry to its
        // own literal shape and 'abbr' is absent from the ones without it.
        // The declared interface is the shape the file actually promises.
        const entry: GlossaryEntry = GLOSSARY[id]
        const term = entry.label[language] ?? entry.label.en
        const body = entry.definition[language] ?? entry.definition.en
        return { id, term, body, abbr: entry.abbr }
      })
      .filter((entry) => matches(query, entry.term, entry.body, entry.id))
      .sort((a, b) => a.term.localeCompare(b.term, language))
  }, [query, language])

  if (entries.length === 0) return null
  const shown = query.trim() || expanded ? entries : entries.slice(0, 8)

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <BookOpen className="size-4 text-brand" aria-hidden />
            {t('help.glossary')}
          </span>
        }
        description={t('help.glossaryHint')}
      />
      <div className="divide-y divide-line">
        {shown.map((entry) => (
          <div key={entry.id} className="px-4 py-3">
            <p className="flex items-baseline gap-2 text-sm font-medium">
              {entry.term}
              {entry.abbr ? (
                <span className="font-mono text-xs text-subtle">{entry.abbr}</span>
              ) : null}
            </p>
            <p className="mt-0.5 text-sm text-muted">{entry.body}</p>
          </div>
        ))}
      </div>
      {!query.trim() && entries.length > shown.length ? (
        <CardBody className="border-t border-line">
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="flex items-center gap-1 text-xs font-medium text-brand hover:underline"
          >
            <ChevronDown className="size-3.5" aria-hidden />
            {t('help.showAllTerms', { count: entries.length })}
          </button>
        </CardBody>
      ) : null}
    </Card>
  )
}

// ---------------------------------------------------------------------------
const PROBLEMS = ['stale', 'offline', 'noAssets', 'noAlerts', 'mqtt', 'permissions']

function TroubleshootingCard({ query }: { query: string }) {
  const { t } = useTranslation()

  const visible = PROBLEMS.filter((key) =>
    matches(query, t(`help.problems.${key}.title`), t(`help.problems.${key}.body`)),
  )

  return (
    <Card>
      <CardHeader title={t('help.troubleshooting')} />
      {visible.length === 0 ? (
        <EmptyState icon={<Search className="size-5" />} title={t('common.noResults')} />
      ) : (
        <div className="divide-y divide-line">
          {visible.map((key) => (
            <details key={key} className="group px-4 py-3">
              <summary className="cursor-pointer list-none text-sm font-medium marker:hidden">
                <span className="flex items-center gap-1.5">
                  <ChevronRight
                    className="size-3.5 shrink-0 text-subtle transition-transform group-open:rotate-90"
                    aria-hidden
                  />
                  {t(`help.problems.${key}.title`)}
                </span>
              </summary>
              <p className="mt-2 pl-5 text-sm text-muted">
                {t(`help.problems.${key}.body`)}
              </p>
            </details>
          ))}
        </div>
      )}
    </Card>
  )
}

/**
 * What this particular install is running.
 *
 * Included because half the "it is broken" questions are really "live ingest
 * was never switched on here", and that is invisible from any other screen.
 */
function EnvironmentCard() {
  const { t } = useTranslation()
  const capabilities = useCapabilities()
  const data = capabilities.data
  if (!data) return null

  return (
    <Card>
      <CardHeader title={t('help.environment')} description={t('help.environmentHint')} />
      <CardBody className="space-y-2 text-sm">
        <Row label={t('help.liveIngest')}>
          <Badge tone={data.mqtt_enabled ? 'ok' : 'neutral'}>
            {data.mqtt_enabled ? t('common.enabled') : t('common.disabled')}
          </Badge>
        </Row>
        <Row label={t('help.sparkplugNamespace')}>
          <code className="font-mono text-xs">{data.sparkplug_namespace}</code>
        </Row>
        <Row label={t('help.sparkplugHostId')}>
          <code className="font-mono text-xs">{data.sparkplug_host_id}</code>
        </Row>
        <Row label={t('help.messageBus')}>
          <code className="font-mono text-xs">{data.bus_backend}</code>
        </Row>
        <Row label={t('help.database')}>
          <code className="font-mono text-xs">{data.database_engine}</code>
        </Row>
        {!data.mqtt_enabled ? (
          <p className="rounded-lg bg-surface-muted px-3 py-2 text-xs text-muted">
            {t('help.mqttDisabledHint')}
          </p>
        ) : null}
        <a
          href="/api/docs"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
        >
          {t('help.apiDocs')}
          <ExternalLink className="size-3" aria-hidden />
        </a>
      </CardBody>
    </Card>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted">{label}</span>
      {children}
    </div>
  )
}

export default HelpPage
