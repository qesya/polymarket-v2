import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts'
import { CHART } from '../../lib/constants'
import { fmt } from '../../lib/formatters'

interface Props { data: Array<{ date: string; pnl: number }> }

export default function PnlBarChart({ data }: Props) {
  if (!data.length) return <Empty />
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
        <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 11 }}
          tickFormatter={d => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          interval="preserveStartEnd" />
        <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} tickFormatter={v => fmt.usd(v)} width={70} />
        <Tooltip
          contentStyle={{ background: '#1a1d27', border: '1px solid #2a2d3a', borderRadius: 8 }}
          labelStyle={{ color: '#9ca3af', fontSize: 12 }}
          formatter={(v: number) => [fmt.usd(v), 'PnL']}
        />
        <ReferenceLine y={0} stroke="#2a2d3a" />
        <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.pnl >= 0 ? CHART.green : CHART.red} fillOpacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

const Empty = () => <div className="h-48 flex items-center justify-center text-muted text-sm">No data</div>
