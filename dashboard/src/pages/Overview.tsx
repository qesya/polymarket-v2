import { useOverview } from '../api/endpoints/overview'
import { useDrawdownHistory } from '../api/endpoints/risk'
import StatCard from '../components/shared/StatCard'
import CircuitBreakerPanel from '../components/circuit/CircuitBreakerPanel'
import PnlBarChart from '../components/charts/PnlBarChart'
import DrawdownChart from '../components/charts/DrawdownChart'
import { fmt } from '../lib/formatters'
import clsx from 'clsx'

const AGENTS = ['market_scanner', 'research', 'prediction', 'risk', 'execution', 'learning']
const AGENT_LABELS: Record<string, string> = {
  market_scanner: 'Scanner', research: 'Research', prediction: 'Prediction',
  risk: 'Risk', execution: 'Execution', learning: 'Learning',
}

export default function Overview() {
  const { data, isLoading } = useOverview()
  const { data: drawdown } = useDrawdownHistory(30)

  if (isLoading) return <Spinner />

  const d = data!
  const pnlHistory = drawdown?.map(p => ({ date: p.date, pnl: p.pnl })) ?? []

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Overview</h1>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard label="Portfolio Value"  value={fmt.usd(d.portfolio_value)}       sub={`Cash: ${fmt.usd(d.cash_available)}`} />
        <StatCard label="Daily PnL"        value={fmt.usd(d.daily_pnl)}             trend={d.daily_pnl >= 0 ? 'up' : 'down'} />
        <StatCard label="Win Rate (30d)"   value={fmt.pct(d.win_rate_30d)}          sub={`${d.total_trades_30d} trades`} />
        <StatCard label="Drawdown"         value={fmt.pct(d.current_drawdown_pct)}  alert={d.current_drawdown_pct > 0.15} trend="down" />
        <StatCard label="Open Positions"   value={String(d.open_position_count)}    sub={`of 20 max`} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* PnL history */}
        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Daily PnL (30d)</h2>
          <PnlBarChart data={pnlHistory} />
        </div>

        {/* Drawdown */}
        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Drawdown (30d)</h2>
          <DrawdownChart data={drawdown ?? []} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Circuit breakers */}
        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Circuit Breakers</h2>
          <CircuitBreakerPanel breakers={d.circuit_breakers} />
        </div>

        {/* Agent health */}
        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium mb-4">Agent Health</h2>
          <div className="space-y-3">
            {AGENTS.map(name => {
              const h = d.agent_health?.[name]
              return (
                <div key={name} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={clsx('w-2 h-2 rounded-full', h?.healthy !== false ? 'bg-emerald-500' : 'bg-red-500')} />
                    <span className="text-sm">{AGENT_LABELS[name]}</span>
                  </div>
                  <div className="text-xs text-muted mono">
                    {h ? `${h.avg_cycle_seconds.toFixed(1)}s · ${h.error_count} err` : '—'}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

const Spinner = () => (
  <div className="flex items-center justify-center h-64">
    <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
  </div>
)
