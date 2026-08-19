# ZQS Cloud console

React front end for the ZQS Cloud energy device platform.

## Stack

| Concern | Choice | Why |
| --- | --- | --- |
| Build | Vite 6 + TypeScript (strict) | fast dev server, typed API surface |
| UI | React 19 | — |
| Routing | React Router 7 | nested layout route, lazy route chunks |
| Server state | TanStack Query 5 | caching, background refetch, invalidation |
| Styling | Tailwind CSS 4 | semantic tokens in `src/index.css` |
| Charts | Recharts | time series, stacked energy balance |
| Map | Leaflet + react-leaflet | OpenStreetMap tiles, no API key needed |
| i18n | i18next | English, 繁體中文, 简体中文 |

## Running

```bash
npm install
npm run dev          # http://127.0.0.1:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so run the Django API
alongside it. Point somewhere else with `VITE_PROXY_TARGET`, or build against an
absolute API origin with `VITE_API_BASE_URL`.

```bash
npm run build        # tsc -b && vite build  ->  dist/
npm run typecheck
npm run preview
```

## Layout

```
src/
  lib/
    api.ts          fetch client: token storage, single-flight refresh, org header
    types.ts        API response types, mirroring the Ninja schemas
    queries.ts      every TanStack Query hook, keyed per resource
    errors.ts       API error code -> translated sentence
    format.ts       locale-aware numbers, units, dates, durations
    useTimeRange.ts rolling window anchored so it does not refetch forever
  i18n/             setup + three locale files (en is the key source of truth)
  providers/        Theme, Auth, Toast
  components/
    layout/         AppShell, Sidebar, TopBar
    ui/             Button, Card, Badge, Field, Table, Modal, StatTile, states
    charts/         TimeSeriesChart, EnergyCharts, PowerFlowDiagram, chartTheme
  pages/            one file per route
```

## Notes on the parts that are easy to get wrong

**Token refresh is single-flight.** A dashboard fires half a dozen queries at
once; if each one refreshed independently on a 401, they would burn six refresh
tokens and trip the server's reuse detection, logging the user out. `api.ts`
shares one refresh promise between all waiters.

**Theme is applied before first paint.** A small inline script in `index.html`
reads the stored preference and sets the `dark` class, so there is no flash of
the wrong palette while React boots. The preference is also saved to the user's
account, so it follows them to another browser.

**Charts read real colour values, not CSS variables.** SVG presentation
attributes do not accept `var(--x)`, so `chartTheme.ts` resolves the palette
with `getComputedStyle` and re-resolves it whenever the theme flips.

**Chart gaps stay gaps.** Series are merged onto one time axis with `null` for
missing samples and `connectNulls={false}`, so an outage draws as a break rather
than a straight line pretending data existed.

**Tailwind only sees literal class strings.** Anything like `` `text-${align}` ``
is never emitted; the table components map to real class names instead.

**The time range is anchored.** `useTimeRange` recomputes `start`/`end` only
when the range changes or `refresh()` is called. Recomputing per render would
change the query key continuously and refetch forever.

## Feature map

| Requirement | Where |
| --- | --- |
| Account and permission management | `pages/SettingsPage.tsx` — members, roles, API keys, password |
| Multi-device status and registered names | `pages/DevicesPage.tsx`, `DeviceDetailPage.tsx` |
| Device locations on a map | `pages/MapPage.tsx` — device GPS, falling back to the site |
| Choosing which time series to record | `pages/RecordingPage.tsx` — interval, deadband, heartbeat, retention |
| Device alarms and operation records | `pages/AlertsPage.tsx`, device log tab, `pages/AuditPage.tsx` |
| Light / dark theme | `providers/ThemeProvider.tsx`, toggle in the top bar and settings |
| Multi-language | `i18n/`, switchable from the login screen and the top bar |
| Behind-the-meter storage | `pages/StoragePage.tsx` + `components/charts/` |

## Deploying

`npm run build` emits a static `dist/`. Serve it from any static host and point
`VITE_API_BASE_URL` at the API, or serve it from the same origin behind a
reverse proxy that routes `/api` to Django — then no env var is needed.

The router uses history mode, so the host must rewrite unknown paths to
`index.html`.
