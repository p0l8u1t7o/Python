import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Building2, ChevronDown, ChevronRight, CornerDownRight, MapPin, Maximize2 } from 'lucide-react'

import { useDeviceMap, useFleetLive, useSites } from '@/lib/queries'
import { useTheme } from '@/providers/ThemeProvider'
import { CATEGORY_ICON } from '@/components/ui/DeviceIcon'
import type { DemandStatus, DeviceMapPoint, Severity, SiteLive, SiteSummary } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  DeviceIcon,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatTile,
  TextInput,
} from '@/components/ui'

const SEVERITY_COLOR: Record<Severity, string> = {
  info: 'var(--info)',
  warning: 'var(--warning)',
  major: 'var(--major)',
  critical: 'var(--critical)',
}

/**
 * Taiwan, framed so the whole island fits at the default size.
 *
 * Used only until the site list arrives - after that the map frames whatever
 * the tenant actually has, which may well be one plant or three countries.
 */
const TAIWAN_CENTER: [number, number] = [23.7, 121.0]
const TAIWAN_ZOOM = 7

/** Bubble radius in pixels, by how many devices the site holds. */
function bubbleRadius(count: number): number {
  // Square root, not linear: a bubble's *area* is what the eye reads as
  // quantity, so scaling the radius linearly would make a site with ten times
  // the devices look a hundred times bigger.
  return Math.max(11, Math.min(34, 9 + Math.sqrt(count) * 5))
}

function markerFor(point: DeviceMapPoint): L.DivIcon {
  const ring = point.highest_severity
    ? SEVERITY_COLOR[point.highest_severity]
    : point.status === 'online'
      ? 'var(--ok)'
      : point.status === 'offline'
        ? 'var(--critical)'
        : 'var(--content-subtle)'

  const badge =
    point.open_alert_count > 0
      ? `<span style="position:absolute;top:-5px;right:-5px;min-width:15px;height:15px;
            padding:0 3px;border-radius:8px;background:${ring};color:#fff;font-size:9px;
            font-weight:700;line-height:15px;text-align:center;
            box-shadow:0 0 0 2px var(--surface)">${point.open_alert_count > 9 ? '9+' : point.open_alert_count}</span>`
      : ''

  // The category glyph is drawn as an inline SVG path rather than mounting a
  // React icon: Leaflet wants an HTML string, and a marker that re-renders per
  // pan would be far more expensive than this.
  const glyph = categoryPath(point.category)

  return L.divIcon({
    className: 'zqs-marker',
    html: `<div style="position:relative;width:26px;height:26px">
             <span style="display:flex;align-items:center;justify-content:center;
                          width:26px;height:26px;border-radius:50%;
                          background:var(--surface);border:3px solid ${ring};
                          box-shadow:0 2px 6px rgb(0 0 0 / .3)">
               <svg viewBox="0 0 24 24" width="13" height="13" fill="none"
                    stroke="${ring}" stroke-width="2.4" stroke-linecap="round"
                    stroke-linejoin="round">${glyph}</svg>
             </span>
             ${badge}
           </div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    popupAnchor: [0, -14],
  })
}

/**
 * A simple silhouette per category, for the map marker.
 *
 * Deliberately not the lucide paths: at 13 px inside a ring, a detailed glyph
 * turns to mud. These are the same *ideas* as {@link CATEGORY_ICON} reduced to
 * two or three strokes, which is what survives at that size.
 */
function categoryPath(category: string): string {
  switch (category) {
    case 'battery':
    case 'pcs':
      return '<rect x="2" y="7" width="16" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/>'
    case 'generation':
      return '<circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/>'
    case 'meter':
      return '<circle cx="12" cy="12" r="9"/><line x1="12" y1="12" x2="16" y2="9"/>'
    case 'generator':
      return '<path d="M4 20V7l6-4v17"/><path d="M10 10h8v10h-8"/>'
    case 'ev_charger':
      return '<rect x="6" y="3" width="12" height="18" rx="2"/><line x1="10" y1="8" x2="10" y2="11"/><line x1="14" y1="8" x2="14" y2="11"/>'
    case 'sensor':
      return '<path d="M12 3v10"/><circle cx="12" cy="17" r="4"/>'
    case 'gateway':
      return '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 9a7 7 0 0 1 10 0"/>'
    case 'load':
      return '<path d="M9 18h6"/><path d="M12 3a6 6 0 0 1 4 10v3H8v-3a6 6 0 0 1 4-10z"/>'
    default:
      return '<rect x="4" y="4" width="16" height="16" rx="3"/><line x1="9" y1="9" x2="15" y2="9"/>'
  }
}

/** Keeps the viewport framed on a set of coordinates. */
function FitBounds({
  points,
  token,
  maxZoom = 15,
}: {
  points: [number, number][]
  token: number
  maxZoom?: number
}) {
  const map = useMap()
  useEffect(() => {
    if (points.length === 0) return
    if (points.length === 1) {
      map.setView(points[0], Math.min(maxZoom, 14))
      return
    }
    map.fitBounds(L.latLngBounds(points), { padding: [48, 48], maxZoom })
  }, [map, points, token, maxZoom])
  return null
}

/** Leaflet measures its container on mount; a hidden or resized one needs a nudge. */
function InvalidateOnMount() {
  const map = useMap()
  useEffect(() => {
    const timer = window.setTimeout(() => map.invalidateSize(), 80)
    return () => window.clearTimeout(timer)
  }, [map])
  return null
}

const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'

/** Fly the map to one point when `token` changes. */
function FlyTo({ target, token }: { target: [number, number] | null; token: number }) {
  const map = useMap()
  useEffect(() => {
    if (target) map.flyTo(target, Math.max(map.getZoom(), 16), { duration: 0.6 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])
  return null
}

/**
 * The fleet on a map: a statistics banner, a searchable site/device panel,
 * and one large map. Selecting a site swaps the map from site bubbles to
 * that site's device markers; selecting a device flies to it.
 */
export function MapPage() {
  const { t } = useTranslation()
  const { resolved } = useTheme()
  // Subtree totals: a plant's bubble should count the devices of its
  // workshops, otherwise the parent reads as empty and the map is misleading.
  const sites = useSites({ includeDescendants: true })
  const [siteId, setSiteId] = useState('')
  const [search, setSearch] = useState('')

  const points = useDeviceMap(siteId || undefined)
  // Live power per site colours the bubbles: the map is where "who is over
  // their contract right now" should be answerable without opening anything.
  const live = useFleetLive()
  const liveBySite = useMemo(
    () => new Map((live.data?.sites ?? []).map((row) => [row.site_id, row])),
    [live.data],
  )
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [fitToken, setFitToken] = useState(0)
  const [flyTarget, setFlyTarget] = useState<[number, number] | null>(null)
  const [flyToken, setFlyToken] = useState(0)
  const initiallyFitted = useRef(false)

  const locatedSites = useMemo(
    () =>
      (sites.data?.items ?? []).filter(
        (site) => site.latitude !== null && site.longitude !== null,
      ),
    [sites.data],
  )

  const locatedDevices = useMemo(
    () =>
      (points.data ?? []).filter(
        (point) => point.latitude !== null && point.longitude !== null,
      ),
    [points.data],
  )

  const selected = locatedSites.find((site) => site.id === siteId)
  const byId = useMemo(() => new Map((sites.data?.items ?? []).map((site) => [site.id, site])), [sites.data])

  // Parent → child links drawn on the map; only pairs where both ends have a
  // location, and never a link to oneself.
  const links = useMemo(() => {
    const out: { id: string; from: [number, number]; to: [number, number]; parent: SiteSummary; child: SiteSummary }[] = []
    for (const site of locatedSites) {
      const parent = site.parent_id ? byId.get(site.parent_id) : undefined
      if (parent && parent.latitude !== null && parent.longitude !== null && parent.id !== site.id) {
        out.push({
          id: site.id,
          from: [parent.latitude, parent.longitude],
          to: [site.latitude!, site.longitude!],
          parent,
          child: site,
        })
      }
    }
    return out
  }, [locatedSites, byId])

  // A grouping site (no meter of its own) takes the worst standing among
  // its descendants, so a park turns red when any of its plants is over.
  const statusOf = useMemo(() => {
    const rank: Record<DemandStatus, number> = { over: 5, high: 4, watch: 3, balanced: 2, exporting: 1, unknown: 0 }
    const all = sites.data?.items ?? []
    const cache = new Map<string, DemandStatus>()
    const resolve = (id: string, depth = 0): DemandStatus => {
      const cached = cache.get(id)
      if (cached) return cached
      let status: DemandStatus = liveBySite.get(id)?.demand_status ?? 'unknown'
      if (status === 'unknown' && depth < 20) {
        for (const child of all.filter((site) => site.parent_id === id)) {
          const childStatus = resolve(child.id, depth + 1)
          if (rank[childStatus] > rank[status]) status = childStatus
        }
      }
      cache.set(id, status)
      return status
    }
    return (id: string) => resolve(id)
  }, [liveBySite, sites.data])

  const demandCounts = useMemo(() => {
    const counts: Record<DemandStatus, number> = { over: 0, high: 0, watch: 0, balanced: 0, exporting: 0, unknown: 0 }
    for (const row of live.data?.sites ?? []) counts[row.demand_status] += 1
    return counts
  }, [live.data])

  // The banner reflects the current scope: the whole fleet, or the selected
  // site once one is chosen.
  const stats = useMemo(() => {
    const list = points.data ?? []
    return {
      total: list.length,
      online: list.filter((point) => point.status === 'online').length,
      offline: list.filter((point) => point.status === 'offline').length,
      alerting: list.filter((point) => point.open_alert_count > 0).length,
    }
  }, [points.data])

  const query = search.trim().toLowerCase()
  // Depth-first tree order with collapse; a search flattens to matches only.
  const visibleSites = useMemo(() => {
    const all = sites.data?.items ?? []
    if (query) {
      return all.filter(
        (site) => site.name.toLowerCase().includes(query) || site.code.toLowerCase().includes(query),
      )
    }
    const children = new Map<string | null, SiteSummary[]>()
    for (const site of all) {
      const key = site.parent_id && all.some((s) => s.id === site.parent_id) ? site.parent_id : null
      children.set(key, [...(children.get(key) ?? []), site])
    }
    const out: SiteSummary[] = []
    const walk = (parent: string | null) => {
      for (const site of (children.get(parent) ?? []).sort((a, b) => a.name.localeCompare(b.name))) {
        out.push(site)
        if (!collapsed.has(site.id)) walk(site.id)
      }
    }
    walk(null)
    return out
  }, [sites.data, query, collapsed])
  const visibleDevices = useMemo(
    () =>
      query
        ? locatedDevices.filter(
            (point) =>
              point.name.toLowerCase().includes(query) ||
              point.device_id.toLowerCase().includes(query),
          )
        : locatedDevices,
    [locatedDevices, query],
  )

  // Frame the fleet once, when the site list first arrives; re-frame when
  // the selection changes - picking a site is a request to look at it.
  useEffect(() => {
    if (!initiallyFitted.current && locatedSites.length > 0) {
      initiallyFitted.current = true
      setFitToken((value) => value + 1)
    }
  }, [locatedSites.length])
  useEffect(() => {
    setFitToken((value) => value + 1)
  }, [siteId, locatedDevices.length])

  const fitCoordinates = useMemo(
    () =>
      siteId
        ? locatedDevices.map(
            (point) => [point.latitude, point.longitude] as [number, number],
          )
        : locatedSites.map(
            (site) => [site.latitude!, site.longitude!] as [number, number],
          ),
    [siteId, locatedDevices, locatedSites],
  )

  if (sites.isPending) {
    return (
      <>
        <PageHeader title={t('map.title')} description={t('map.subtitle')} />
        <LoadingState />
      </>
    )
  }
  if (sites.error) {
    return (
      <>
        <PageHeader title={t('map.title')} description={t('map.subtitle')} />
        <ErrorState error={sites.error} onRetry={() => void sites.refetch()} />
      </>
    )
  }
  if (locatedSites.length === 0) {
    return (
      <>
        <PageHeader title={t('map.title')} description={t('map.subtitle')} />
        <Card>
          <EmptyState
            icon={<MapPin className="size-6" />}
            title={t('map.noLocations')}
            action={
              <Link to="/sites" className="text-sm font-medium text-brand hover:underline">
                {t('sites.title')}
              </Link>
            }
          />
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={t('map.title')}
        description={
          selected ? `${selected.name} — ${selected.address || selected.code}` : t('map.subtitle')
        }
        actions={
          selected ? (
            <Button size="sm" onClick={() => setSiteId('')}>
              {t('map.backToFleet')}
            </Button>
          ) : null
        }
      />

      {/* ---- Statistics banner ------------------------------------------- */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label={t('map.stats.total')}
          value={String(stats.total)}
          icon={<Building2 className="size-4" />}
        />
        <StatTile
          label={t('map.stats.online')}
          value={String(stats.online)}
          accent="ok"
          icon={<MapPin className="size-4" />}
        />
        <StatTile
          label={t('map.stats.offline')}
          value={String(stats.offline)}
          accent="critical"
          icon={<MapPin className="size-4" />}
        />
        <StatTile
          label={t('map.stats.alerting')}
          value={String(stats.alerting)}
          accent="warning"
          icon={<MapPin className="size-4" />}
        />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="map-demand-stats">
        <StatTile
          label={t('map.demand.over')}
          value={String(demandCounts.over + demandCounts.high)}
          hint={t('map.demand.overHint')}
          accent="critical"
          icon={<Building2 className="size-4" />}
        />
        <StatTile
          label={t('map.demand.watch')}
          value={String(demandCounts.watch)}
          hint={t('map.demand.watchHint')}
          accent="warning"
          icon={<Building2 className="size-4" />}
        />
        <StatTile
          label={t('map.demand.balanced')}
          value={String(demandCounts.balanced + demandCounts.exporting)}
          hint={t('map.demand.balancedHint')}
          accent="ok"
          icon={<Building2 className="size-4" />}
        />
        <StatTile
          label={t('map.demand.unknown')}
          value={String(demandCounts.unknown)}
          hint={t('map.demand.unknownHint')}
          accent="neutral"
          icon={<Building2 className="size-4" />}
        />
      </div>

      <div className="mt-4 flex min-h-[480px] gap-4" style={{ height: 'calc(100vh - 330px)' }}>
        {/* ---- Side panel ------------------------------------------------ */}
        <Card className="flex w-80 shrink-0 flex-col overflow-hidden p-0">
          <div className="border-b border-line p-3">
            <TextInput
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t('map.searchPlaceholder')}
            />
          </div>
          <div className="flex-1 overflow-y-auto">
            {!selected ? (
              <div className="divide-y divide-line">
                {visibleSites.map((site) => {
                  const row = liveBySite.get(site.id)
                  const status: DemandStatus = statusOf(site.id)
                  const hasChildren = site.child_count > 0
                  const isCollapsed = collapsed.has(site.id)
                  const parent = site.parent_id ? byId.get(site.parent_id) : undefined
                  return (
                    <div
                      key={site.id}
                      className="flex w-full items-center gap-1.5 px-3 py-2 hover:bg-surface-muted"
                      style={{ paddingLeft: 10 + (query ? 0 : site.depth) * 16 }}
                      data-testid={`map-site-${site.code}`}
                    >
                      {hasChildren && !query ? (
                        <button
                          type="button"
                          onClick={() =>
                            setCollapsed((current) => {
                              const next = new Set(current)
                              if (next.has(site.id)) next.delete(site.id)
                              else next.add(site.id)
                              return next
                            })
                          }
                          aria-expanded={!isCollapsed}
                          aria-label={isCollapsed ? t('common.expand') : t('common.collapse')}
                          className="rounded p-0.5 text-subtle hover:text-default"
                        >
                          {isCollapsed ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
                        </button>
                      ) : site.depth > 0 && !query ? (
                        <CornerDownRight className="size-3.5 shrink-0 text-subtle" aria-hidden />
                      ) : (
                        <span className="inline-block w-[1.125rem]" aria-hidden />
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          setSiteId(site.id)
                          setSearch('')
                        }}
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      >
                        <span
                          className="size-2.5 shrink-0 rounded-full"
                          style={{ background: demandColor(status) }}
                          title={t(`map.demandStatus.${status}`)}
                          aria-hidden
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{site.name}</span>
                          <span className="block truncate text-[11px] text-muted">
                            {t('map.siteCounts', { online: site.total_online_count, total: site.total_device_count })}
                            {row && !row.is_stale && row.flow.grid_kw !== null
                              ? ` · ${t('storage.grid')} ${row.flow.grid_kw.toFixed(0)} kW${row.demand_ceiling_kw ? ` / ${row.demand_ceiling_kw.toFixed(0)}` : ''}`
                              : ''}
                            {parent && query ? ` · ${t('map.belongsTo', { site: parent.name })}` : ''}
                          </span>
                        </span>
                      </button>
                      {site.total_open_alert_count > 0 ? (
                        <Badge tone="critical">{site.total_open_alert_count}</Badge>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="divide-y divide-line">
                {visibleDevices.map((point) => (
                  <button
                    key={point.id}
                    type="button"
                    onClick={() => {
                      setFlyTarget([point.latitude, point.longitude])
                      setFlyToken((value) => value + 1)
                    }}
                    className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-surface-muted"
                  >
                    <DeviceIcon category={point.category} className="size-4 shrink-0 text-muted" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {point.name || point.device_id}
                      </span>
                      <span className="block truncate text-[11px] text-muted">
                        {point.device_id}
                      </span>
                    </span>
                    <span
                      className={`size-2 shrink-0 rounded-full ${
                        point.status === 'online'
                          ? 'bg-ok'
                          : point.status === 'offline'
                            ? 'bg-critical'
                            : 'bg-subtle'
                      }`}
                      aria-hidden
                    />
                    {point.open_alert_count > 0 ? (
                      <Badge tone="critical">{point.open_alert_count}</Badge>
                    ) : null}
                  </button>
                ))}
                {visibleDevices.length === 0 ? (
                  <p className="p-4 text-xs text-muted">{t('map.noDevicesHere')}</p>
                ) : null}
              </div>
            )}
          </div>
          <div className="border-t border-line p-2 text-center text-[11px] text-muted">
            {selected
              ? t('map.panelDevices', { count: visibleDevices.length })
              : t('map.panelSites', { count: visibleSites.length })}
          </div>
        </Card>

        {/* ---- The map --------------------------------------------------- */}
        <Card className="relative flex-1 overflow-hidden p-0">
          <MapContainer
            center={TAIWAN_CENTER}
            zoom={TAIWAN_ZOOM}
            scrollWheelZoom
            className="size-full"
            // Remounting on theme change lets the tile filter apply cleanly.
            key={`map-${resolved}`}
          >
            <TileLayer attribution={TILE_ATTRIBUTION} url={TILE_URL} maxZoom={19} />
            <InvalidateOnMount />
            <FitBounds
              points={fitCoordinates}
              token={fitToken}
              maxZoom={siteId ? 17 : 11}
            />
            <FlyTo target={flyTarget} token={flyToken} />

            {!siteId
              ? links.map((link) => (
                  <Polyline
                    key={`link-${link.id}`}
                    positions={[link.from, link.to]}
                    pathOptions={{ color: 'var(--brand)', weight: 2, opacity: 0.7, dashArray: '6 6' }}
                  >
                    <Tooltip sticky>
                      {link.parent.name} → {link.child.name}
                    </Tooltip>
                  </Polyline>
                ))
              : null}
            {!siteId
              ? locatedSites.map((site) => (
                  <SiteBubble
                    key={site.id}
                    site={site}
                    live={liveBySite.get(site.id)}
                    status={statusOf(site.id)}
                    parent={site.parent_id ? byId.get(site.parent_id) : undefined}
                    selected={false}
                    onSelect={() => setSiteId(site.id)}
                  />
                ))
              : locatedDevices.map((point) => (
                  <Marker
                    key={point.id}
                    position={[point.latitude, point.longitude]}
                    icon={markerFor(point)}
                  >
                    <Popup>
                      <DevicePopup point={point} />
                    </Popup>
                  </Marker>
                ))}
          </MapContainer>
          <div className="absolute right-3 top-3 z-[1000]">
            <Button
              size="sm"
              icon={<Maximize2 className="size-3.5" />}
              onClick={() => setFitToken((value) => value + 1)}
            >
              {siteId ? t('map.fitToDevices') : t('map.fitToSites')}
            </Button>
          </div>
        </Card>
      </div>

      <MapLegend
        shown={locatedDevices.length}
        total={points.data?.length ?? 0}
        categories={locatedDevices}
        fleetView={!siteId}
      />
    </>
  )
}

/**
 * One site as a bubble sized by its device count.
 *
 * A `CircleMarker` rather than a `Circle`: the radius is in *pixels*, so the
 * bubble keeps its meaning at every zoom. A metres-based circle would swell
 * into a blob covering the island as you zoom out, which reads as coverage
 * area rather than as a count.
 */
/** Bubble colour per demand standing; alerts get a ring, not the fill. */
function demandColor(status: DemandStatus): string {
  switch (status) {
    case 'over':
      return 'var(--critical)'
    case 'high':
      return 'var(--major, #ea580c)'
    case 'watch':
      return 'var(--warning)'
    case 'balanced':
      return 'var(--ok)'
    case 'exporting':
      return 'var(--info)'
    default:
      return 'var(--content-subtle)'
  }
}

function SiteBubble({
  site,
  live,
  status,
  parent,
  selected,
  onSelect,
}: {
  site: SiteSummary
  live?: SiteLive
  status: DemandStatus
  parent?: SiteSummary
  selected: boolean
  onSelect: () => void
}) {
  const { t } = useTranslation()
  const hasAlerts = site.total_open_alert_count > 0
  const allOnline =
    site.total_device_count > 0 && site.total_online_count === site.total_device_count
  // Fill says demand standing; the ring says "there are open alerts". Two
  // channels, two questions - a site can be perfectly balanced and alarming.
  const color = demandColor(status)
  const ring = hasAlerts ? 'var(--critical)' : color
  const isGroup = site.child_count > 0

  return (
    <CircleMarker
      center={[site.latitude!, site.longitude!]}
      radius={bubbleRadius(site.total_device_count) + (isGroup ? 4 : 0)}
      pathOptions={{
        color: ring,
        weight: hasAlerts ? 4 : selected ? 4 : isGroup ? 3 : 2,
        dashArray: isGroup ? '4 4' : undefined,
        fillColor: color,
        fillOpacity: status === 'over' || status === 'high' ? 0.55 : selected ? 0.45 : 0.3,
        className: status === 'over' ? 'zqs-bubble-over' : undefined,
      }}
      eventHandlers={{ click: onSelect }}
    >
      {/* Permanent, because the number is the whole point of the bubble -
          a count you have to hover for is not an overview. */}
      <Tooltip permanent direction="center" className="zqs-bubble-label">
        {site.total_device_count}
      </Tooltip>
      <Popup>
        <div className="min-w-48 space-y-1.5">
          <p className="text-sm font-semibold text-content">{site.name}</p>
          {site.address ? <p className="text-xs text-subtle">{site.address}</p> : null}
          {parent ? (
            <p className="text-xs text-muted">{t('map.belongsTo', { site: parent.name })}</p>
          ) : null}
          <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
            <Badge tone={allOnline ? 'ok' : 'neutral'}>
              {site.total_online_count}/{site.total_device_count} {t('dashboard.online')}
            </Badge>
            {hasAlerts ? (
              <Badge tone="critical">{site.total_open_alert_count}</Badge>
            ) : null}
            <Badge tone={status === 'over' ? 'critical' : status === 'high' ? 'major' : status === 'watch' ? 'warning' : status === 'balanced' ? 'ok' : status === 'exporting' ? 'info' : 'neutral'}>
              {t(`map.demandStatus.${status}`)}
            </Badge>
          </div>
          {live && !live.is_stale && live.flow.grid_kw !== null ? (
            <p className="text-xs text-content">
              {t('storage.grid')} <span className="font-mono font-semibold">{live.flow.grid_kw.toFixed(1)} kW</span>
              {live.demand_ceiling_kw ? (
                <span className="text-muted">
                  {' '}/ {t('map.ceiling')} {live.demand_ceiling_kw.toFixed(0)} kW
                  {live.contract_capacity_kw ? ` · ${t('map.contract')} ${live.contract_capacity_kw.toFixed(0)} kW` : ''}
                </span>
              ) : null}
              {live.flow.battery_kw !== null && Math.abs(live.flow.battery_kw) > 0.05 ? (
                <span className="text-muted">
                  {' '}· {t('storage.battery')} {live.flow.battery_kw > 0 ? '+' : ''}{live.flow.battery_kw.toFixed(1)} kW
                </span>
              ) : null}
            </p>
          ) : null}
          {site.child_count > 0 ? (
            <p className="text-xs text-muted">
              {t('dashboard.groupChildren', { count: site.child_count })}
            </p>
          ) : null}
          <button
            type="button"
            onClick={onSelect}
            className="mt-1 text-xs font-medium text-brand hover:underline"
          >
            {selected ? t('map.clearSite') : t('map.showDevices')}
          </button>
        </div>
      </Popup>
    </CircleMarker>
  )
}

function DevicePopup({ point }: { point: DeviceMapPoint }) {
  const { t } = useTranslation()
  return (
    <div className="min-w-52 space-y-1.5">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-content">
        <DeviceIcon category={point.category} />
        {point.name}
      </p>
      <p className="font-mono text-[11px] text-muted">{point.device_id}</p>
      <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
        <Badge
          tone={
            point.status === 'online'
              ? 'ok'
              : point.status === 'offline'
                ? 'critical'
                : 'neutral'
          }
        >
          {t(`status.${point.status}`)}
        </Badge>
        {point.category ? (
          <Badge tone="neutral">
            {t(`devices.categories.${point.category}`, { defaultValue: point.category })}
          </Badge>
        ) : null}
        {point.open_alert_count > 0 ? (
          <Badge tone="critical">
            {t('devices.openAlerts', { count: point.open_alert_count })}
          </Badge>
        ) : null}
      </div>
      {point.site_name ? <p className="text-xs text-muted">{point.site_name}</p> : null}
      {point.address ? <p className="text-xs text-subtle">{point.address}</p> : null}
      <p className="text-[11px] text-subtle">
        {point.source === 'site' ? t('map.fromSite') : t('map.fromDevice')}
      </p>
      <Link
        to={`/devices/${point.id}`}
        className="mt-1 inline-block text-xs font-medium text-brand hover:underline"
      >
        {t('common.details')} →
      </Link>
    </div>
  )
}

function MapLegend({
  shown,
  total,
  categories,
  fleetView,
}: {
  shown: number
  total: number
  categories: DeviceMapPoint[]
  fleetView: boolean
}) {
  const { t } = useTranslation()
  if (fleetView) {
    const statuses: DemandStatus[] = ['over', 'high', 'watch', 'balanced', 'exporting', 'unknown']
    return (
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted" data-testid="map-legend">
        <span className="font-medium">{t('map.legend')}:</span>
        {statuses.map((status) => (
          <span key={status} className="flex items-center gap-1.5">
            <span className="size-3 rounded-full" style={{ background: demandColor(status), opacity: 0.8 }} aria-hidden />
            {t(`map.demandStatus.${status}`)}
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="size-3 rounded-full border-2 border-critical" aria-hidden />
          {t('map.stats.alerting')}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-3 rounded-full border-2 border-dashed border-brand" aria-hidden />
          {t('map.groupBubble')}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-6 border-t-2 border-dashed border-brand" aria-hidden />
          {t('map.linkLegend')}
        </span>
      </div>
    )
  }

  // Only the categories actually on the map: a legend listing eleven kinds of
  // equipment when three are present is noise, not help.
  const present = useMemo(() => {
    const seen = new Set<string>()
    categories.forEach((point) => {
      if (point.category && point.category in CATEGORY_ICON) seen.add(point.category)
    })
    return [...seen].sort()
  }, [categories])

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted">
      <span className="font-medium">{t('map.legend')}:</span>
      {[
        { color: 'var(--ok)', label: t('status.online') },
        { color: 'var(--critical)', label: t('status.offline') },
        { color: 'var(--content-subtle)', label: t('status.unknown') },
      ].map((entry) => (
        <span key={entry.label} className="flex items-center gap-1.5">
          <span
            className="size-3 rounded-full border-[3px] bg-surface"
            style={{ borderColor: entry.color }}
            aria-hidden
          />
          {entry.label}
        </span>
      ))}

      {present.length > 0 ? <span className="text-line">|</span> : null}
      {present.map((category) => (
        <span key={category} className="flex items-center gap-1.5">
          <DeviceIcon category={category} className="size-3.5" />
          {t(`devices.categories.${category}`, { defaultValue: category })}
        </span>
      ))}

      <span className="ml-auto text-subtle">
        {shown} / {total}
      </span>
    </div>
  )
}

/** Vite needs the default export for lazy route loading. */
export default MapPage
