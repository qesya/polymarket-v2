import { useRiskSummary, useDrawdownHistory } from '../api/endpoints/risk'
import StatCard from '../components/shared/StatCard'
import CircuitBreakerPanel from '../components/circuit/CircuitBreakerPanel'
import DrawdownChart from '../components/charts/DrawdownChart'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { CHART } from '../lib/constants'
import { fmt } from '../lib/formatters'

export default function Risk() {
  const { data: risk, isLoading } = useRiskSummary()
  const { data: drawdown = [] }   = useDrawdownHistory(30)

  if (isLoading || !risk) return (
    <div className="flex items-center justify-center h-64">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  )

  const ddPct  = risk.current_drawdown_pct
  const ddPct2 = risk.max_drawdown_pct
  const dailyLossPct = risk.daily_pnl < 0 ? Math.abs(risk.daily_pnl) : 0

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Risk Management</h1>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Drawdown"
          value={fmt.pct(ddPct)}
          sub={`Limit: ${fmt.pct(ddPct2)}`}
          alert={ddPct > ddPct2 * 0.75}
          trend="down"
        />
        <StatCard
          label="Daily Loss"
          value={fmt.pct(dailyLossPct)}
          sub={`Limit: ${fmt.pct(risk.daily_loss_limit_pct)}`}
          alert={dailyLossPct > risk.daily_loss_limit_pct * 0.75}
        />
        <StatCard
          label="Open Positions"
          value={`${risk.current_open_positions} / ${risk.max_open_positions}`}
          alert={risk.current_open_positions >= risk.max_open_positions}
        />
        <StatCard
          label="Kelly Fraction"
          value={fmt.pct(risk.kelly_fraction)}
          sub="Fractional Kelly"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Drawdown History (30d)</h2>
          <DrawdownChart data={drawdown} maxDrawdown={risk.max_drawdown_pct} />
        </div>

        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Circuit Breakers</h2>
          <CircuitBreakerPanel breakers={risk.circuit_breakers} />
        </div>
      </div>

      {risk.rejection_reasons.length > 0 && (
        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Trade Rejection Reasons (30d)</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={risk.rejection_reasons} layout="vertical" margin={{ left: 120 }}>
              <XAxis type="number" tick={{ fill: '#6b7280', fontSize: 11 }} />
              <YAxis type="category" dataKey="reason" tick={{ fill: '#9ca3af', fontSize: 12 }} width={115} />
              <Tooltip
                contentStyle={{ background: '#1a1d27', border: '1px solid #2a2d3a', borderRadius: 8 }}
                formatter={(v: number) => [v, 'rejections']}
              />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {risk.rejection_reasons.map((_, i) => (
                  <Cell key={i} fill={CHART.blue} fillOpacity={0.8} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
