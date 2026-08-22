import { useTranslation } from 'react-i18next'

import { useChartColors } from './chartTheme'

/**
 * A state-of-charge dial.
 *
 * An arc rather than a bar because SOC is the one figure on the page that is
 * bounded on both ends - 0 and 100 are real, fixed limits, and a dial says so
 * without needing an axis label. Everything else here is unbounded power.
 *
 * Drawn as inline SVG rather than pulled from a chart library: it is one path
 * and a number, and Recharts' RadialBarChart brings a responsive container,
 * a data array and a legend to do the same job.
 */
export function SocGauge({
  percent,
  size = 132,
  /** Drawn as a notch, so "how close to the floor is it" is visible. */
  reserve = null,
  label,
  stale = false,
}: {
  percent: number | null
  size?: number
  reserve?: number | null
  label?: string
  stale?: boolean
}) {
  const { t } = useTranslation()
  const colors = useChartColors()

  const stroke = 12
  const radius = (size - stroke) / 2
  const centre = size / 2

  /**
   * A ring with a wedge missing at the **bottom**.
   *
   * Angles here run clockwise from twelve o'clock: 0 is up, 90 right, 180
   * down, 270 left. So a gap centred on the bottom spans
   * `180 ± gap/2`, and the arc is everything else - starting where the gap
   * ends and sweeping the rest of the way round.
   *
   * Derived rather than written as constants. The previous version hard-coded
   * a start of 135°, which put the opening on the *right* and pushed the arc
   * through the bottom of the box, where it was clipped.
   */
  const gap = 90
  const startAngle = 180 + gap / 2
  const sweep = 360 - gap
  const circumference = 2 * Math.PI * radius
  const arcLength = (circumference * sweep) / 360

  const clamped = percent === null ? 0 : Math.max(0, Math.min(100, percent))
  const filled = (arcLength * clamped) / 100

  // Colour by how much room is left, not by a brand palette: the whole point
  // of showing SOC is that low is a different situation from high.
  const tone =
    percent === null
      ? colors.axis
      : clamped <= 15
        ? colors.critical
        : clamped <= 30
          ? colors.warning
          : colors.ok

  const polar = (angle: number) => {
    const radians = ((angle - 90) * Math.PI) / 180
    return [centre + radius * Math.cos(radians), centre + radius * Math.sin(radians)]
  }
  const [startX, startY] = polar(startAngle)
  const [endX, endY] = polar(startAngle + sweep)
  // large-arc-flag follows the sweep rather than being assumed: anything past
  // a half turn needs it set, and a smaller gap than 180° always is.
  const largeArc = sweep > 180 ? 1 : 0
  const track = `M ${startX} ${startY} A ${radius} ${radius} 0 ${largeArc} 1 ${endX} ${endY}`

  /**
   * Tall enough for the arc that is actually drawn.
   *
   * The lowest ink is the stroke's outer edge at one of the two arc ends, both
   * of which sit at `gap/2` either side of straight down. Measuring it instead
   * of guessing a fraction of `size` is what stops the dial being clipped when
   * the gap or the stroke changes.
   */
  const lowestInk = centre + radius * Math.sin(((startAngle - 90) * Math.PI) / 180) + stroke / 2
  const height = Math.ceil(lowestInk) + 2

  const reserveAngle =
    reserve === null ? null : startAngle + (sweep * Math.max(0, Math.min(100, reserve))) / 100

  return (
    <div className="flex flex-col items-center">
      <svg
        width={size}
        height={height}
        viewBox={`0 0 ${size} ${height}`}
        role="img"
        aria-label={`${label ?? t('storage.soc')} ${percent === null ? '—' : `${clamped}%`}`}
      >
        <path
          d={track}
          fill="none"
          stroke={colors.grid}
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {percent !== null ? (
          <path
            d={track}
            fill="none"
            stroke={tone}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${filled} ${circumference}`}
            opacity={stale ? 0.45 : 1}
          />
        ) : null}

        {reserveAngle !== null
          ? (() => {
              const [innerX, innerY] = polar(reserveAngle)
              const outer = radius + stroke / 2 + 3
              const radians = ((reserveAngle - 90) * Math.PI) / 180
              return (
                <line
                  x1={innerX}
                  y1={innerY}
                  x2={centre + outer * Math.cos(radians)}
                  y2={centre + outer * Math.sin(radians)}
                  stroke={colors.critical}
                  strokeWidth={2}
                />
              )
            })()
          : null}

        <text
          x={centre}
          y={centre + 4}
          textAnchor="middle"
          fontSize={size * 0.2}
          fontWeight={600}
          fill={colors.content}
          className="tnum"
        >
          {percent === null ? '—' : `${Math.round(clamped)}`}
        </text>
        {percent !== null ? (
          <text
            x={centre}
            y={centre + size * 0.16}
            textAnchor="middle"
            fontSize={size * 0.1}
            fill={colors.axis}
          >
            %
          </text>
        ) : null}
      </svg>
      {label ? <p className="mt-1 text-xs text-muted">{label}</p> : null}
    </div>
  )
}
