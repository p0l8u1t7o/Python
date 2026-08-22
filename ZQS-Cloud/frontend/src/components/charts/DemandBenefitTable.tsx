import { useTranslation } from 'react-i18next'

import { formatCurrency, formatMeasurement } from '@/lib/format'
import type { SiteCost } from '@/lib/types'
import { Table, TBody, Td, Th, THead, Tr } from '@/components/ui/Table'

/**
 * The capacity side of the bill, one row per site with a contract.
 *
 * Demand charge is billed on the month's highest 15-minute average, so the
 * row compares two peaks: what the meter recorded and what it would have
 * been with the battery idle. The money column prices the difference at the
 * plan tariff's monthly rate and adds whatever excess penalty was avoided.
 */
export function DemandBenefitTable({
  sites,
  currency,
}: {
  sites: SiteCost[]
  currency?: string
}) {
  const { t } = useTranslation()
  const rows = sites.filter(
    (site) => site.baseline_peak_kw !== null && site.baseline_peak_kw !== undefined,
  )
  if (rows.length === 0) return null

  return (
    <div className="mt-5 overflow-x-auto">
      <Table>
        <THead>
          <Th>{t('dashboard.demandSite')}</Th>
          <Th align="right">{t('dashboard.demandContract')}</Th>
          <Th align="right">{t('dashboard.demandBaseline')}</Th>
          <Th align="right">{t('dashboard.demandActual')}</Th>
          <Th align="right">{t('dashboard.demandReduction')}</Th>
          <Th align="right">{t('dashboard.demandSavings')}</Th>
        </THead>
        <TBody>
          {rows.map((site) => {
            const reduction =
              (site.baseline_peak_kw ?? 0) - (site.peak_demand_kw ?? 0)
            const overContract =
              site.contract_capacity_kw !== null &&
              site.contract_capacity_kw !== undefined &&
              (site.peak_demand_kw ?? 0) > site.contract_capacity_kw
            const baselineOver =
              site.contract_capacity_kw !== null &&
              site.contract_capacity_kw !== undefined &&
              (site.baseline_peak_kw ?? 0) > site.contract_capacity_kw
            return (
              <Tr key={site.site_id}>
                <Td>
                  <span style={{ paddingLeft: `${site.depth * 12}px` }}>{site.site_name}</span>
                </Td>
                <Td align="right" className="font-mono tabular-nums">
                  {site.contract_capacity_kw
                    ? formatMeasurement(site.contract_capacity_kw, 'kW', 0)
                    : '—'}
                </Td>
                <Td align="right" className="font-mono tabular-nums">
                  <span className={baselineOver ? 'text-critical' : undefined}>
                    {formatMeasurement(site.baseline_peak_kw, 'kW', 0)}
                  </span>
                </Td>
                <Td align="right" className="font-mono tabular-nums">
                  <span className={overContract ? 'text-critical' : 'text-ok'}>
                    {formatMeasurement(site.peak_demand_kw, 'kW', 0)}
                  </span>
                </Td>
                <Td align="right" className="font-mono tabular-nums">
                  {formatMeasurement(reduction, 'kW', 0)}
                </Td>
                <Td align="right" className="font-mono tabular-nums">
                  {site.demand_charge_per_kw <= 0 ? (
                    <span className="text-xs text-muted" title={t('dashboard.demandNoRateHint')}>
                      {t('dashboard.demandNoRate')}
                    </span>
                  ) : (
                  <span className={site.demand_savings < 0 ? 'text-critical' : 'text-ok'}>
                    {formatCurrency(site.demand_savings, currency || site.currency)}
                  </span>
                  )}
                  {site.penalty_avoided > 0 ? (
                    <span className="ml-1 text-xs text-muted">
                      {t('dashboard.demandPenalty', {
                        amount: formatCurrency(site.penalty_avoided, currency || site.currency),
                      })}
                    </span>
                  ) : null}
                </Td>
              </Tr>
            )
          })}
        </TBody>
      </Table>
      <p className="mt-2 text-xs text-muted">{t('dashboard.demandHint')}</p>
    </div>
  )
}
