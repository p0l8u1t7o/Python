/** Shapes returned by the ZQS Cloud API. Mirrors the Ninja schemas. */

export type Role = 'owner' | 'admin' | 'operator' | 'viewer'
export type ThemePreference = 'system' | 'light' | 'dark'
export type ConnectionStatus = 'online' | 'offline' | 'unknown'
export type Severity = 'info' | 'warning' | 'major' | 'critical'
export type AlertStatus = 'firing' | 'acknowledged' | 'resolved'
export type EventLevel = 'debug' | 'info' | 'notice' | 'warning' | 'error' | 'critical'
export type CommandStatus =
  | 'pending'
  | 'sent'
  | 'accepted'
  | 'succeeded'
  | 'rejected'
  | 'failed'
  | 'expired'
  | 'cancelled'

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown }
}

// ---------------------------------------------------------------------------
// Accounts
// ---------------------------------------------------------------------------
export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  refresh_expires_in: number
}

export interface User {
  id: string
  email: string
  full_name: string
  phone: string
  is_active: boolean
  is_staff: boolean
  language: string
  theme: ThemePreference
  timezone_name: string
  created_at: string
  last_login: string | null
}

export interface Organization {
  id: string
  name: string
  slug: string
  is_active: boolean
  default_timezone: string
  created_at: string
}

export interface OrganizationMembership {
  organization: Organization
  role: Role
}

export interface Me {
  user: User
  organization: Organization
  role: Role
  organizations: OrganizationMembership[]
  permissions: string[]
}

export interface Member {
  user: User
  role: Role
  created_at: string
}

export interface ApiKey {
  id: string
  name: string
  prefix: string
  role: Role
  is_active: boolean
  expires_at: string | null
  revoked_at: string | null
  last_used_at: string | null
  created_at: string
}

export interface ApiKeyCreated {
  key: ApiKey
  secret: string
}

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------
export type SiteKind = 'site' | 'area' | 'line' | 'group'

export interface Site {
  id: string
  name: string
  code: string
  /** Null for a top-level site. */
  parent_id: string | null
  kind: SiteKind
  /** 0 for a top-level site, 1 for its children, and so on. */
  depth: number
  child_count: number
  description: string
  address: string
  city: string
  region: string
  country: string
  postal_code: string
  latitude: number | null
  longitude: number | null
  timezone_name: string
  contact_name: string
  contact_phone: string
  tags: string[]
  is_active: boolean
  created_at: string
}

export interface SiteSummary extends Site {
  /** Devices assigned to this site itself. */
  device_count: number
  online_count: number
  open_alert_count: number
  /**
   * The same counts including every descendant site. Equal to the plain counts
   * unless the request asked for `include_descendants`.
   */
  total_device_count: number
  total_online_count: number
  total_open_alert_count: number
}

/**
 * `peak_basis` says how to read the peak figures. `measured` is one site's own
 * meter; `coincident_estimate` means several sites were summed per interval and
 * the largest of those sums taken - an upper bound, never the sum of each
 * site's individual peak.
 */
export interface SiteEnergyRollup {
  start: string
  end: string
  site_count: number
  grid_import_kwh: number
  grid_export_kwh: number
  pv_kwh: number
  load_kwh: number
  battery_charge_kwh: number
  battery_discharge_kwh: number
  peak_import_kw: number | null
  peak_load_kw: number | null
  peak_basis: 'measured' | 'coincident_estimate'
  energy_cost: number
  export_revenue: number
  estimated_savings: number
  self_consumption_ratio: number | null
  self_sufficiency_ratio: number | null
  round_trip_efficiency: number | null
  currency: string
}

export interface SiteRollup {
  site_id: string
  site_name: string
  kind: SiteKind
  depth: number
  include_descendants: boolean
  site_ids: string[]
  site_count: number
  child_count: number
  devices: {
    total: number
    online: number
    offline: number
    unknown: number
    disabled: number
    stale: number
  }
  alerts: {
    open: number
    critical: number
    major: number
    acknowledged: number
  }
  energy: SiteEnergyRollup | null
}

export interface CommandDefinition {
  name: string
  label?: Record<string, string>
  params?: {
    type?: string
    required?: string[]
    properties?: Record<string, CommandParamSpec>
  }
  min_role?: Role
  confirm?: boolean
}

export interface CommandParamSpec {
  type?: 'number' | 'integer' | 'string' | 'boolean'
  minimum?: number
  maximum?: number
  enum?: string[]
  unit?: string
}

export interface Blueprint {
  id: string
  key: string
  name: string
  category: string
  manufacturer: string
  model_name: string
  description: string
  icon: string
  command_definitions: CommandDefinition[]
  organization_id: string | null
  created_at: string
}

export interface DeviceCapabilities {
  can_charge: boolean
  can_discharge: boolean
  can_export: boolean
  is_dispatchable: boolean
}

/**
 * A device's own claims about itself. Shown to an operator as a hint; never
 * consulted when deciding whether a command may run. Accepting one is what
 * moves values into `Device.capabilities`.
 */
export type LifecycleState = 'pending' | 'active' | 'suspended' | 'retired' | 'rejected'

export interface DeviceDeclaration {
  device_id: string
  schema_version: number
  /** Agreement, not approval: a category never changes after commissioning. */
  state: 'matched' | 'mismatched' | 'acknowledged'
  received_at: string
  reviewed_at: string | null
  payload: Record<string, unknown>
  diff_summary: Record<string, { declared: unknown; effective: unknown }>
  has_differences: boolean
}

export interface Device {
  id: string
  device_id: string
  name: string
  description: string
  serial_number: string
  status: ConnectionStatus
  status_changed_at: string | null
  last_seen_at: string | null
  last_telemetry_at: string | null
  firmware_version: string
  hardware_version: string
  ip_address: string | null
  rssi: number | null
  latitude: number | null
  longitude: number | null
  address: string
  location_source: string
  tags: string[]
  metadata: Record<string, unknown>
  is_enabled: boolean
  created_at: string
  capabilities: DeviceCapabilities
  capability_source: 'blueprint' | 'manual' | 'device'
  commissioning_state: LifecycleState
  retired_at: string | null
  replaced_by_id: string | null
  /**
   * The device is declaring a different category than it is registered as, so
   * dispatch commands are frozen until a replacement is registered.
   */
  identity_mismatch: boolean
  /** No blueprint, so no capability check is possible. */
  capabilities_unchecked: boolean
  device_category: string
  site_id: string | null
  site_name: string | null
  device_type_id: string | null
  device_type_name: string | null
  recording_policy_id: string | null
}

export interface DeviceReplacement {
  retired: Device
  replacement: Device
  moved_asset_count: number
  moved_alert_rule_count: number
  credential: DeviceCredential | null
}

export interface MetricValue {
  metric_key: string
  label: string
  unit: string
  value: number | null
  value_text: string | null
  ts: string
  quality: number
}

export interface DeviceDetail extends Device {
  latest: MetricValue[]
  open_alert_count: number
  available_commands: CommandDefinition[]
}

export interface DeviceMapPoint {
  id: string
  device_id: string
  name: string
  status: ConnectionStatus
  latitude: number
  longitude: number
  address: string
  source: string
  site_id: string | null
  site_name: string | null
  category: string
  open_alert_count: number
  highest_severity: Severity | null
}

export interface DeviceCredential {
  mqtt_username: string
  mqtt_password: string | null
  allowed_client_id: string
  is_active: boolean
  rotated_at: string | null
  last_auth_at: string | null
}

export interface DeviceCreated {
  device: Device
  credential: DeviceCredential | null
}

export interface Command {
  id: string
  device_id: string
  device_external_id: string
  name: string
  params: Record<string, unknown>
  status: CommandStatus
  issued_by_label: string
  created_at: string
  sent_at: string | null
  acked_at: string | null
  completed_at: string | null
  expires_at: string
  response: Record<string, unknown>
  error: string
}

export interface DeviceEvent {
  id: number
  device_id: string
  device_external_id: string
  ts: string
  level: EventLevel
  code: string
  message: string
  payload: Record<string, unknown>
  received_at: string
}

export interface DeviceStatusEvent {
  id: number
  device_id: string
  status: ConnectionStatus
  previous_status: string
  reason: string
  ts: string
  payload: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Telemetry
// ---------------------------------------------------------------------------
export interface Metric {
  id: string | null
  key: string
  display_name: string
  label: string
  translations: Record<string, string>
  description: string
  unit: string
  value_type: string
  kind: string
  aggregation: string
  decimals: number
  min_value: number | null
  max_value: number | null
  state_map: Record<string, unknown>
  category: string
  is_builtin: boolean
}

export interface RecordingRule {
  id?: number
  metric_key: string
  enabled: boolean
  min_interval_seconds: number
  max_interval_seconds: number
  deadband_absolute: number | null
  deadband_percent: number | null
  retention_days: number | null
  keep_rollups: boolean
}

export interface RecordingPolicy {
  id: string
  name: string
  description: string
  is_default: boolean
  device_type_id: string | null
  record_unlisted_metrics: boolean
  default_retention_days: number
  default_min_interval_seconds: number
  default_max_interval_seconds: number
  rules: RecordingRule[]
  device_count: number
  created_at: string
}

export interface SeriesPoint {
  ts: string
  value: number | null
  min?: number | null
  max?: number | null
  count?: number | null
}

export interface Series {
  device_id: string
  device_external_id: string
  metric_key: string
  label: string
  unit: string
  aggregation: string
  interval_seconds: number
  points: SeriesPoint[]
}

export interface SeriesResponse {
  start: string
  end: string
  interval_seconds: number
  downsampled: boolean
  series: Series[]
}

export interface LatestValue extends MetricValue {
  device_id: string
  device_external_id: string
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------
export type RuleScope = 'organization' | 'site' | 'device_type' | 'device'
export type Operator =
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'eq'
  | 'neq'
  | 'outside'
  | 'inside'
  | 'no_data'
  | 'offline'

export interface AlertRule {
  id: string
  name: string
  description: string
  is_enabled: boolean
  severity: Severity
  scope: RuleScope
  site_id: string | null
  device_type_id: string | null
  device_ids: string[]
  metric_key: string
  operator: Operator
  threshold: number | null
  threshold_upper: number | null
  hysteresis: number
  for_duration_seconds: number
  cooldown_seconds: number
  auto_resolve: boolean
  message_template: string
  channel_ids: string[]
  open_alert_count: number
  created_at: string
}

export interface Alert {
  id: string
  device_id: string | null
  device_external_id: string
  device_name: string
  site_name: string | null
  rule_id: string | null
  rule_name: string | null
  source: 'rule' | 'device' | 'system'
  severity: Severity
  status: AlertStatus
  metric_key: string
  code: string
  title: string
  message: string
  trigger_value: number | null
  threshold: number | null
  details: Record<string, unknown>
  occurrence_count: number
  started_at: string
  last_triggered_at: string
  acknowledged_at: string | null
  acknowledged_by_label: string | null
  acknowledge_note: string
  resolved_at: string | null
  resolve_note: string
}

export interface AlertEvent {
  id: number
  event_type: string
  actor_label: string
  message: string
  value: number | null
  details: Record<string, unknown>
  created_at: string
}

export interface AlertDetail extends Alert {
  events: AlertEvent[]
}

export interface AlertSummary {
  total_open: number
  firing: number
  acknowledged: number
  by_severity: Record<string, number>
  critical_devices: number
}

export interface NotificationChannel {
  id: string
  name: string
  channel_type: 'webhook' | 'email' | 'mqtt'
  is_enabled: boolean
  min_severity: Severity
  config: Record<string, unknown>
  created_at: string
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------
export interface AuditLog {
  id: number
  action: string
  action_label: string
  status: 'success' | 'failure'
  actor_id: string | null
  actor_label: string
  target_type: string
  target_id: string
  target_label: string
  ip_address: string | null
  request_id: string
  payload: Record<string, unknown>
  message: string
  created_at: string
}

// ---------------------------------------------------------------------------
// EMS / behind-the-meter storage
// ---------------------------------------------------------------------------
export type AssetRole =
  | 'grid_meter'
  | 'load_meter'
  | 'pv'
  | 'battery'
  | 'ev_charger'
  | 'generator'

export type DispatchStrategy =
  | 'manual'
  | 'self_consumption'
  | 'peak_shaving'
  | 'tou_arbitrage'
  | 'backup_only'

export interface EnergyAsset {
  id: string
  site_id: string
  device_id: string
  device_external_id: string
  device_name: string
  role: AssetRole
  name: string
  power_metric: string
  energy_import_metric: string
  energy_export_metric: string
  soc_metric: string
  soh_metric: string
  power_scale: number
  energy_scale: number
  invert_sign: boolean
  rated_power_kw: number | null
  rated_energy_kwh: number | null
  is_active: boolean
}

export interface StoragePlan {
  id: string
  site_id: string
  strategy: DispatchStrategy
  is_enabled: boolean
  contract_capacity_kw: number | null
  peak_shaving_target_kw: number | null
  export_limit_kw: number | null
  usable_capacity_kwh: number | null
  max_charge_kw: number | null
  max_discharge_kw: number | null
  min_soc_percent: number
  max_soc_percent: number
  backup_reserve_percent: number
  round_trip_efficiency: number
  tariff_id: string | null
  notes: string
  dispatchable_capacity_kwh: number | null
  updated_at: string
}

export interface Tariff {
  id: string
  name: string
  kind: 'flat' | 'tou'
  currency: string
  timezone_name: string
  demand_charge_per_kw: number
  default_import_price: number
  default_export_price: number
  periods: Record<string, unknown>[]
  is_active: boolean
  created_at: string
}

export interface PowerFlow {
  grid_kw: number | null
  pv_kw: number | null
  load_kw: number | null
  battery_kw: number | null
  battery_soc_percent: number | null
  battery_soh_percent: number | null
  as_of: string | null
  is_stale: boolean
}

export interface EnergyTotals {
  start: string
  end: string
  grid_import_kwh: number
  grid_export_kwh: number
  pv_kwh: number
  load_kwh: number
  battery_charge_kwh: number
  battery_discharge_kwh: number
  peak_import_kw: number | null
  energy_cost: number
  export_revenue: number
  estimated_savings: number
  self_consumption_ratio: number | null
  self_sufficiency_ratio: number | null
  round_trip_efficiency: number | null
  currency: string
}

export interface SiteOverview {
  site_id: string
  site_name: string
  strategy: DispatchStrategy | null
  contract_capacity_kw: number | null
  usable_capacity_kwh: number | null
  flow: PowerFlow
  today: EnergyTotals
  device_count: number
  online_count: number
  open_alert_count: number
}

export interface EnergyInterval {
  interval_start: string
  interval_seconds: number
  grid_import_kwh: number
  grid_export_kwh: number
  pv_kwh: number
  load_kwh: number
  battery_charge_kwh: number
  battery_discharge_kwh: number
  peak_import_kw: number | null
  avg_load_kw: number | null
  soc_start_percent: number | null
  soc_end_percent: number | null
  tariff_period: string
  import_price: number | null
  energy_cost: number
  export_revenue: number
  estimated_savings: number
  coverage: number
}

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------
export interface Capabilities {
  languages: { code: string; name: string }[]
  default_language: string
  themes: string[]
  mqtt_topic_root: string
  bus_backend: string
  database_engine: string
  device_offline_grace_seconds: number
  command_default_timeout_seconds: number
  max_page_size: number
}

export interface FleetStats {
  total_devices: number
  online: number
  offline: number
  unknown: number
  disabled: number
  sites: number
  open_alerts: number
}

export interface HealthComponent {
  name: string
  ok: boolean
  detail: string
}

export interface Health {
  status: string
  version: string
  uptime_seconds: number
  server_time: string
  components: HealthComponent[]
}
