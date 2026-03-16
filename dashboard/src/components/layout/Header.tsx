import { useOverview } from '../../api/endpoints/overview'
import { fmt } from '../../lib/formatters'
import clsx from 'clsx'

const CIRCUIT_NAMES = ['api', 'trading', 'model', 'execution'] as const

export default function Header() {
  const { data } = useOverview()

  return (
    <header className="h-14 border-b border-border bg-card flex items-center justify-between px-6 flex-shrink-0">
      {/* Circuit breakers strip */}
      <div className="flex items-center gap-3">
        {CIRCUIT_NAMES.map(name => {
          const cb = data?.circuit_breakers?.[name]
          const open = cb?.is_open ?? false
          return (
            <div key={name} className="flex items-center gap-1.5" title={cb?.reason || ''}>
              <span className={clsx('w-2 h-2 rounded-full', open ? 'bg-red-500 animate-pulse' : 'bg-emerald-500')} />
              <span className={clsx('text-xs uppercase tracking-wide', open ? 'text-red-400' : 'text-muted')}>
                {name}
              </span>
            </div>
          )
        })}
      </div>

      {/* Portfolio summary */}
      {data && (
        <div className="flex items-center gap-6 text-sm">
          <div className="text-center">
            <div className="text-muted text-xs">Portfolio</div>
            <div className="font-medium mono">{fmt.usd(data.portfolio_value)}</div>
          </div>
          <div className="text-center">
            <div className="text-muted text-xs">Daily PnL</div>
            <div className={clsx('font-medium mono', data.daily_pnl >= 0 ? 'text-emerald-400' : 'text-red-400')}>
              {fmt.usd(data.daily_pnl)}
            </div>
          </div>
          <div className="text-center">
            <div className="text-muted text-xs">Drawdown</div>
            <div className={clsx('font-medium mono', data.current_drawdown_pct > 0.1 ? 'text-red-400' : 'text-white')}>
              {fmt.pct(data.current_drawdown_pct)}
            </div>
          </div>
        </div>
      )}
    </header>
  )
}
