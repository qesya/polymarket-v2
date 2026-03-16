import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { CHART } from '../../lib/constants'
import { fmt } from '../../lib/formatters'
import type { DrawdownPoint } from '../../types/api'

interface Props { data: DrawdownPoint[]; maxDrawdown?: number }

export default function DrawdownChart({ data, maxDrawdown = 0.2 }: Props) {
  if (!data.length) return <div className="h-48 flex items-center justify-center text-muted text-sm">No data</div>
  const mapped = data.map(d => ({ ...d, dd: -(d.drawdown_pct * 100) }))

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={mapped} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={CHART.red} stopOpacity={0.3} />
            <stop offset="95%" stopColor={CHART.red} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 11 }}
          tickFormatter={d => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          interval="preserveStartEnd" />
        <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} tickFormatter={v => `${v.toFixed(1)}%`} width={52} />
        <Tooltip
          contentStyle={{ background: '#1a1d27', border: '1px solid #2a2d3a', borderRadius: 8 }}
          formatter={(v: number) => [`${Math.abs(v).toFixed(2)}%`, 'Drawdown']}
        />
        <ReferenceLine y={-(maxDrawdown * 100)} stroke={CHART.amber} strokeDasharray="4 2"
          label={{ value: 'Limit', fill: CHART.amber, fontSize: 10 }} />
        <Area type="monotone" dataKey="dd" stroke={CHART.red} fill="url(#ddGrad)" strokeWidth={1.5} />
      </AreaChart>
    </ResponsiveContainer>
  )
}
