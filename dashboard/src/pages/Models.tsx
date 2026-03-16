import { useModelPerformance } from '../api/endpoints/models'
import StatCard from '../components/shared/StatCard'
import CalibrationChart from '../components/charts/CalibrationChart'
import EnsembleWeightChart from '../components/charts/EnsembleWeightChart'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { CHART } from '../lib/constants'
import { fmt } from '../lib/formatters'

export default function Models() {
  const { data, isLoading } = useModelPerformance()
  if (isLoading) return <Spinner />
  if (!data) return null

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Model Performance</h1>
        <div className="text-xs text-muted mono">v{data.current_version} · deployed {fmt.ago(data.deployed_at)}</div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="XGBoost Brier"  value={fmt.brier(data.xgb_brier_score)}  sub="Lower is better" />
        <StatCard label="LightGBM Brier" value={fmt.brier(data.lgbm_brier_score)} sub="Lower is better" />
        <StatCard label="Training Samples" value={fmt.num(data.training_samples)} />
        <StatCard label="Ensemble (XGB/LGBM/Claude)"
          value={`${fmt.pct(data.weights.xgb)} / ${fmt.pct(data.weights.lgbm)} / ${fmt.pct(data.weights.claude)}`} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Calibration (predicted vs actual)</h2>
          <CalibrationChart data={data.calibration} />
          <p className="text-xs text-muted mt-2">Points on the diagonal = perfectly calibrated model</p>
        </div>

        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Ensemble Weights</h2>
          <EnsembleWeightChart weights={data.weights} />
        </div>
      </div>

      {/* Accuracy history */}
      {data.accuracy_history.length > 0 && (
        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Prediction Accuracy (60d)</h2>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={data.accuracy_history}>
              <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 11 }}
                tickFormatter={d => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                interval="preserveStartEnd" />
              <YAxis domain={[0, 1]} tick={{ fill: '#6b7280', fontSize: 11 }}
                tickFormatter={v => `${(v * 100).toFixed(0)}%`} width={42} />
              <Tooltip
                contentStyle={{ background: '#1a1d27', border: '1px solid #2a2d3a', borderRadius: 8 }}
                formatter={(v: number) => [`${(v * 100).toFixed(1)}%`, 'Accuracy']}
              />
              <Line type="monotone" dataKey="accuracy" stroke={CHART.blue} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Version history */}
      {data.version_history.length > 0 && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-border text-sm font-medium">Version History</div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted uppercase">
                <th className="text-left px-5 py-3">Version</th>
                <th className="text-right px-4 py-3">XGB Brier</th>
                <th className="text-right px-4 py-3">LGBM Brier</th>
                <th className="text-right px-4 py-3">Samples</th>
                <th className="text-right px-5 py-3">Deployed</th>
              </tr>
            </thead>
            <tbody>
              {data.version_history.map((v, i) => (
                <tr key={v.version} className="border-b border-border/50">
                  <td className="px-5 py-3 mono text-xs">
                    {v.version}
                    {i === 0 && <span className="ml-2 px-1.5 py-0.5 bg-accent/20 text-accent text-xs rounded">current</span>}
                  </td>
                  <td className="px-4 py-3 text-right mono">{fmt.brier(v.xgb_brier_score)}</td>
                  <td className="px-4 py-3 text-right mono">{fmt.brier(v.lgbm_brier_score)}</td>
                  <td className="px-4 py-3 text-right mono text-muted">{fmt.num(v.training_samples)}</td>
                  <td className="px-5 py-3 text-right text-muted">{fmt.date(v.deployed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const Spinner = () => (
  <div className="flex items-center justify-center h-64">
    <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
  </div>
)
