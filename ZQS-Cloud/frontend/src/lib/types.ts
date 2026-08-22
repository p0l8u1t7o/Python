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
  /** ISO 4217. Every money figure is already in this currency. */
  reporting_currency: string
}

export interface OrganizationMembership {
  organization: Organization
  role: Role
}

/** A blob of console layout state. The server stores it and never reads it. */
export interface UiPreference {
  key: string
  value: Record<string, unknown>
}

export interface Me {
  user: User
  organization: Organization
  role: Role
  organizations: OrganizationMembership[]
  permissions: string[]
  /**
   * Sites this session may see, already expanded to include descendants.
   * Empty means the whole organization. Used to explain why a page looks
   * smaller than expected - the API enforces it, the console only says so.
   */
  site_scope: string[]
  /** The sites actually granted, before subtree expansion. */
  scoped_site_ids: string[]
}

export interface Member {
  user: User
  role: Role
  created_at: string
  /** Sites this member is restricted to. Empty means the whole organization. */
  site_ids: string[]
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
  /** `name` and `description` in the reader's language. */
  label: string
  description_text: string
  translations: Record<string, { name?: string; description?: string }>
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

export interface DeviceCost {
  capital_cost: number | null
  cost_currency: string
  commissioned_on: string | null
  expected_life_years: number | null
  annual_maintenance_cost: number | null
  /** Amortised capital plus upkeep. Null means unknown, never "free". */
  annual_cost: number | null
}

export interface EdgeNode {
  id: string
  node_id: string
  group_id: string
  name: string
  description: string
  is_implicit: boolean
  is_enabled: boolean
  status: ConnectionStatus
  status_changed_at: string | null
  last_seen_at: string | null
  birth_at: string | null
  /** Birth/death sequence of the session currently believed to be live. */
  bd_seq: number | null
  /** Last accepted payload sequence number, 0-255. */
  last_seq: number | null
  rebirth_requested_at: string | null
  firmware_version: string
  hardware_version: string
  ip_address: string | null
  rssi: number | null
  site_id: string | null
  site_name: string | null
  device_count: number
  created_at: string
}

export interface Device extends DeviceCost {
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
  /** The Sparkplug edge node this device reports through. */
  edge_node_id: string | null
  edge_node_name: string
  /**
   * True when the node exists only to carry this device, i.e. the device
   * speaks MQTT itself. The console hides plumbing the operator never asked
   * for, so a gateway is only worth showing when it is a real one.
   */
  edge_node_is_implicit: boolean
  /** `group_id/edge_node_id/device_id` - the address on the broker. */
  sparkplug_address: string
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
  device_name: string
  site_id: string | null
  site_name: string | null
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
  channel_type: 'webhook' | 'email' | 'line' | 'mqtt'
  is_enabled: boolean
  min_severity: Severity
  /** Rule-engine alerts subscription. */
  notify_alerts: boolean
  /** Device-reported events subscription. */
  notify_events: boolean
  min_event_level: string
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
  | 'demand_cap'
  | 'tou_arbitrage'
  | 'backup_only'
  | 'workflow'

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
  /** Detect charge / discharge / running sessions for this asset. */
  session_tracking_enabled: boolean
  session_enter_kw: number | null
  session_exit_kw: number | null
  session_min_duration_s: number
  session_gap_s: number
  /** Registered cost-model key; blank falls back to the role default. */
  cost_model: string
  cost_parameters: Record<string, unknown>
}

export type SessionKind = 'charge' | 'discharge' | 'running'

export interface OperatingSession {
  id: number
  device_id: string
  device_name: string
  device_external_id: string
  site_id: string | null
  kind: SessionKind
  started_at: string
  /** Null means still in progress - correct for equipment that never stops. */
  ended_at: string | null
  duration_s: number | null
  energy_kwh: number
  peak_kw: number | null
  avg_kw: number | null
  start_soc_percent: number | null
  end_soc_percent: number | null
  end_reason: string
}

export interface SessionSummary {
  kind: SessionKind
  count: number
  total_energy_kwh: number
  total_duration_s: number
  avg_duration_s: number | null
  max_peak_kw: number | null
  last_started_at: string | null
  open_count: number
}

export interface DeviceEnergy {
  device_id: string
  metric_key: string
  /** `counter` is exact, `integrated` is approximate, `unknown` is honest. */
  basis: 'counter' | 'integrated' | 'unknown'
  /** Null means "cannot be determined" - never zero. */
  kwh: number | null
  unit: string
  coverage: number
  samples: number
  counter_reset: boolean
  avg_kw: number | null
  peak_kw: number | null
  start: string
  end: string
  available_metrics: string[]
}

export type CostSource = 'grid' | 'battery' | 'generator' | 'ev' | 'other'

export interface CostBreakdownRow {
  source: CostSource
  cost_model: string
  energy_kwh: number
  /** Positive is a cost, negative a revenue. Never clamped at zero. */
  amount: number
  unit_cost: number | null
  basis: 'measured' | 'estimated' | 'unknown'
}

export interface CostBreakdown {
  site_id: string
  start: string
  end: string
  currency: string
  total_amount: number
  rows: CostBreakdownRow[]
  /** Intervals with no computable baseline - an outage, or savings disabled. */
  unknown_savings_intervals: number
}

export interface CostModel {
  key: string
  default_for: string[]
}

export interface SiteCost {
  site_id: string
  site_name: string
  parent_id: string | null
  depth: number
  energy_cost: number
  export_revenue: number
  estimated_savings: number
  grid_import_kwh: number
  load_kwh: number
  device_count: number
  currency: string
}

export interface CostOverview {
  start: string
  end: string
  currency: string
  total_energy_cost: number
  total_export_revenue: number
  total_estimated_savings: number
  /** Sites disagree on currency, so the totals must not be shown as money. */
  mixed_currency: boolean
  sites: SiteCost[]
}

export interface DispatchDecision {
  site_id: string
  site_name: string
  device_id: string | null
  device_external_id: string
  /** Watts. Negative charges, positive discharges. */
  power_w: number | null
  window_id: string | null
  reason: string
  clamped_from_w: number | null
  skipped: string
}

export interface StoragePlan {
  id: string
  /** Plans are named templates; sites bind to one. */
  name: string
  /** Sites currently driven by this plan. */
  sites: { id: string; name: string }[]
  /** On the per-site endpoint: the ancestor the plan is inherited from. */
  inherited_from?: string | null
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
  workflow_id: string | null
  notes: string
  dispatchable_capacity_kwh: number | null
  updated_at: string
  /** What "savings" is measured against. */
  savings_baseline: 'grid_only' | 'no_storage' | 'none'
  /** Turn the plan's limits into a hard gate on dispatch commands. */
  enforce_limits: boolean
  /** Demand ceiling for the demand-cap strategy; null = 95% of contract. */
  demand_cap_target_kw: number | null
  /** Whether demand-cap recharges during the tariff's cheapest period. */
  offpeak_recharge: boolean
  /** Arbitrage acts only when today's price spread clears this (per kWh). */
  min_price_spread: number
  /** Full-cycle-equivalents allowed per day; null disables the cap. */
  max_cycles_per_day: number | null
  /** Above this temperature the engine stops driving the battery. */
  temperature_max_c: number | null
  /** Metric key on the battery device carrying that temperature. */
  temperature_metric: string
}

/** One committed demand-response dispatch. Overrides everything while live. */
export interface DemandResponseEvent {
  id: string
  site_id: string
  starts_at: string
  ends_at: string
  target_power_kw: number
  cancelled_at: string | null
  note: string
  source: string
  created_at: string
  is_active: boolean
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

/** A bundled Taipower rate table the operator can apply and then edit. */
export interface TariffPreset {
  key: string
  name: string
  description: string
  /** The Taipower tariff year the numbers came from. */
  tariff_year: string
  tariff: {
    kind: 'flat' | 'tou'
    currency: string
    timezone_name: string
    demand_charge_per_kw: number
    default_import_price: number
    default_export_price: number
    periods: Record<string, unknown>[]
  }
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

export interface SiteLive {
  site_id: string
  site_name: string
  parent_id: string | null
  depth: number
  flow: PowerFlow
  device_count: number
  online_count: number
  open_alert_count: number
  today_load_kwh: number
  today_energy_cost: number
  /** Null when a generator was carrying the site - no baseline to compare. */
  today_estimated_savings: number | null
  currency: string
  is_stale: boolean
}

/**
 * Live energy across every visible site.
 *
 * `totals` sums the per-site flows, which is valid: power *does* add across
 * sites at one instant. Peak demand does not, which is why there is no peak
 * figure here - `/ems/sites/{id}/summary` carries that with its caveat.
 */
export interface FleetLive {
  as_of: string | null
  totals: PowerFlow
  /** Capacity-weighted, so a 1 MWh pack outweighs a 10 kWh one. */
  battery_soc_percent: number | null
  site_count: number
  reporting_site_count: number
  currency: string
  mixed_currency: boolean
  today_energy_cost: number
  today_estimated_savings: number
  today_load_kwh: number
  today_pv_kwh: number
  sites: SiteLive[]
}

export interface DeviceInvestment {
  device_id: string
  device_name: string
  device_external_id: string
  category: string
  capital_cost: number | null
  annual_cost: number | null
  commissioned_on: string | null
  expected_life_years: number | null
}

export interface SiteInvestment {
  site_id: string
  start: string
  end: string
  currency: string
  total_capital_cost: number
  total_annual_cost: number
  /** The annual figure apportioned to the window being viewed. */
  window_amortised_cost: number
  /** Counted rather than treated as free, which would flatter the payback. */
  devices_without_cost: number
  devices: DeviceInvestment[]
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
  /**
   * Null when there is no baseline to compare against - during an outage the
   * "buy it from the grid instead" alternative does not exist, so any number
   * would be fiction. Negative is legitimate and means the dispatch cost more
   * than doing nothing would have.
   */
  estimated_savings: number | null
  coverage: number
}

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------
export interface Capabilities {
  languages: { code: string; name: string }[]
  default_language: string
  themes: string[]
  sparkplug_namespace: string
  sparkplug_host_id: string
  /** False when this deployment runs without a broker. */
  mqtt_enabled: boolean
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
  /** "Is this a problem?" - not "is it connected". */
  ok: boolean
  detail: string
  /** `ok` | `error` | `disabled` */
  state: 'ok' | 'error' | 'disabled'
  /** False when this deployment is configured without the dependency. */
  required: boolean
}

export interface Health {
  status: string
  version: string
  uptime_seconds: number
  server_time: string
  components: HealthComponent[]
}


export interface GeocodeResult {
  latitude: number
  longitude: number
  display_name: string
  city: string
  /** ISO 3166-1 alpha-2, upper case. */
  country: string
  /** Blank when the point falls outside any land timezone. */
  timezone_name: string
}

export interface GeocodeResponse {
  /**
   * False when this deployment has geocoding switched off, so the console can
   * say "type the coordinates in" rather than showing an empty result list
   * that looks like a failed search.
   */
  available: boolean
  results: GeocodeResult[]
}


export interface EventCode {
  code: string
  count: number
}
