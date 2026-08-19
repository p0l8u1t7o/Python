import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { MapPin } from 'lucide-react'

import { useDeviceMap, useSites } from '@/lib/queries'
import { useTheme } from '@/providers/ThemeProvider'
import type { DeviceMapPoint, Severity } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Select,
} from '@/components/ui'

const SEVERITY_COLOR: Record<Severity, string> = {
  info: 'var(--info)',
  warning: 'var(--warning)',
  major: 'var(--major)',
  critical: 'var(--critical)',
}

/**
 * Markers are built as divIcons rather than Leaflet's default PNG pins.
 *
 * Two reasons: the bundled default icon needs a webpack-style asset path fix
 * that is easy to get wrong, and a DOM marker can use the same CSS variables as
 * the rest of the console, so it re-themes with everything else.
 */
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

  return L.divIcon({
    className: 'zqs-marker',
    html: `<div style="position:relative;width:22px;height:22px">
             <span style="display:block;width:22px;height:22px;border-radius:50%;
                          background:var(--surface);border:3px solid ${ring};
                          box-shadow:0 2px 6px rgb(0 0 0 / .3)"></span>
             ${badge}
           </div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    popupAnchor: [0, -12],
  })
}

/** Keeps the viewport framed on the current marker set. */
function FitBounds({ points, token }: { points: DeviceMapPoint[]; token: number }) {
  const map = useMap()
  useEffect(() => {
    if (points.length === 0) return
    const bounds = L.latLngBounds(points.map((point) => [point.latitude, point.longitude]))
    map.fitBounds(bounds, { padding: [48, 48], maxZoom: 15 })
  }, [map, points, token])
  return null
}

export function MapPage() {
  const { t } = useTranslation()
  const { resolved } = useTheme()
  const sites = useSites()
  const [siteId, setSiteId] = useState('')
  const points = useDeviceMap(siteId || undefined)
  const [fitToken, setFitToken] = useState(0)
  const initialFit = useRef(false)

  const located = useMemo(
    () => (points.data ?? []).filter((point) => point.latitude !== null && point.longitude !== null),
    [points.data],
  )

  // Frame the fleet once on first load; after that the user stays in control.
  useEffect(() => {
    if (!initialFit.current && located.length > 0) {
      initialFit.current = true
      setFitToken((value) => value + 1)
    }
  }, [located.length])

  const center: [number, number] = located.length
    ? [located[0].latitude, located[0].longitude]
    : [23.7, 121.0]

  return (
    <>
      <PageHeader
        title={t('map.title')}
        description={t('map.subtitle')}
        actions={
          <>
            <Select
              value={siteId}
              placeholder={t('common.all')}
              onChange={(event) => setSiteId(event.target.value)}
              options={(sites.data?.items ?? []).map((site) => ({
                value: site.id,
                label: site.name,
              }))}
              className="w-44"
            />
            <Button
              icon={<MapPin className="size-4" />}
              disabled={located.length === 0}
              onClick={() => setFitToken((value) => value + 1)}
            >
              {t('map.fitToDevices')}
            </Button>
          </>
        }
      />

      <Card className="overflow-hidden">
        {points.isPending ? (
          <LoadingState />
        ) : points.error ? (
          <ErrorState error={points.error} onRetry={() => void points.refetch()} />
        ) : located.length === 0 ? (
          <EmptyState
            icon={<MapPin className="size-6" />}
            title={t('map.noLocations')}
            action={
              <Link to="/sites" className="text-sm font-medium text-brand hover:underline">
                {t('sites.title')}
              </Link>
            }
          />
        ) : (
          <div className="h-[calc(100vh-15rem)] min-h-[420px] w-full">
            <MapContainer
              center={center}
              zoom={9}
              scrollWheelZoom
              className="size-full"
              // Remounting on theme change lets the tile filter apply cleanly.
              key={resolved}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                maxZoom={19}
              />
              <FitBounds points={located} token={fitToken} />
              {located.map((point) => (
                <Marker
                  key={point.id}
                  position={[point.latitude, point.longitude]}
                  icon={markerFor(point)}
                >
                  <Popup>
                    <div className="min-w-52 space-y-1.5">
                      <p className="text-sm font-semibold text-content">{point.name}</p>
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
                        {point.open_alert_count > 0 ? (
                          <Badge tone="critical">
                            {t('devices.openAlerts', { count: point.open_alert_count })}
                          </Badge>
                        ) : null}
                      </div>
                      {point.site_name ? (
                        <p className="text-xs text-muted">{point.site_name}</p>
                      ) : null}
                      {point.address ? (
                        <p className="text-xs text-subtle">{point.address}</p>
                      ) : null}
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
                  </Popup>
                </Marker>
              ))}
            </MapContainer>
          </div>
        )}
      </Card>

      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-muted">
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
        <span className="text-subtle">
          {located.length} / {points.data?.length ?? 0}
        </span>
      </div>
    </>
  )
}

/** Vite needs the default export for lazy route loading. */
export default MapPage
