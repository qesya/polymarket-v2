import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Line, ComposedChart } from 'recharts'
import { CHART } from '../../lib/constants'
import type { CalibrationPoint } from '../../types/api'

interface Props { data: CalibrationPoint[] }

export default function CalibrationChart({ data }: Props) {
  if (!data.length) return <div className="h-48 flex items-center justify-center text-muted text-sm">No calibration data</div>
  const perfect = [{ x: 0, y: 0 }, { x: 1, y: 1 }]

  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart margin={{ top: 4, right: 8, bottom: 24, left: 8 }}>
        <XAxis type="number" dataKey="x" domain={[0, 1]} tick={{ fill: '#6b7280', fontSize: 11 }}
          tickFormatter={v => `${(v * 100).toFixed(0)}%`}
          label={{ value: 'Predicted probability', position: 'insideBottom', offset: -12, fill: '#6b7280', fontSize: 11 }} />
        <YAxis type="number" dataKey="y" domain={[0, 1]} tick={{ fill: '#6b7280', fontSize: 11 }}
          tickFormatter={v => `${(v * 100).toFixed(0)}%`} width={42} />
        <Tooltip
          contentStyle={{ background: '#1a1d27', border: '1px solid #2a2d3a', borderRadius: 8 }}
          formatter={(v: number, name: string) => [`${(v * 100).toFixed(1)}%`, name]}
        />
        {/* Perfect calibration line */}
        <Line data={perfect} type="linear" dataKey="y" stroke={CHART.gray} strokeDasharray="4 2" dot={false} />
        {/* Actual calibration scatter */}
        <Scatter
          data={data.map(d => ({ x: d.predicted_bucket, y: d.actual_rate, count: d.count }))}
          fill={CHART.blue} opacity={0.9}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
