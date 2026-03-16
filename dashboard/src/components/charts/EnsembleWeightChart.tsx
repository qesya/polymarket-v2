import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { CHART } from '../../lib/constants'
import type { EnsembleWeights } from '../../types/api'

const COLORS = [CHART.blue, CHART.green, CHART.purple]
const LABELS = ['XGBoost', 'LightGBM', 'Claude']

export default function EnsembleWeightChart({ weights }: { weights: EnsembleWeights }) {
  const data = [
    { name: 'XGBoost',  value: weights.xgb },
    { name: 'LightGBM', value: weights.lgbm },
    { name: 'Claude',   value: weights.claude },
  ]

  return (
    <ResponsiveContainer width="100%" height={200}>
      <PieChart>
        <Pie data={data} cx="50%" cy="50%" innerRadius={55} outerRadius={80}
          dataKey="value" paddingAngle={3}>
          {data.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}
        </Pie>
        <Tooltip
          contentStyle={{ background: '#1a1d27', border: '1px solid #2a2d3a', borderRadius: 8 }}
          formatter={(v: number) => [`${(v * 100).toFixed(1)}%`]}
        />
        <Legend formatter={(v) => <span style={{ color: '#9ca3af', fontSize: 12 }}>{v}</span>} />
      </PieChart>
    </ResponsiveContainer>
  )
}
