import { usePositions } from '../api/endpoints/positions'
import PnlCell from '../components/shared/PnlCell'
import { fmt } from '../lib/formatters'
import clsx from 'clsx'

export default function Positions() {
  const { data = [], isLoading } = usePositions()

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Open Positions</h1>
        <span className="text-sm text-muted">{data.length} position{data.length !== 1 ? 's' : ''}</span>
      </div>

      <div className="bg-card border border-border rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-10 text-center text-muted text-sm">Loading…</div>
        ) : data.length === 0 ? (
          <div className="p-10 text-center text-muted text-sm">No open positions</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted uppercase tracking-wide">
                <th className="text-left px-5 py-3">Market</th>
                <th className="text-center px-4 py-3">Side</th>
                <th className="text-right px-4 py-3">Shares</th>
                <th className="text-right px-4 py-3">Avg Entry</th>
                <th className="text-right px-4 py-3">Current</th>
                <th className="text-right px-4 py-3">Unrealized</th>
                <th className="text-right px-4 py-3">Realized</th>
                <th className="text-right px-5 py-3">Opened</th>
              </tr>
            </thead>
            <tbody>
              {data.map(p => (
                <tr key={p.market_id} className="border-b border-border/50 hover:bg-white/2 transition-colors">
                  <td className="px-5 py-3">
                    <div className="max-w-xs truncate font-medium" title={p.question}>{p.question}</div>
                    <div className="text-xs text-muted mt-0.5">{p.category}</div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={clsx('px-2 py-0.5 rounded text-xs font-medium',
                      p.side === 'YES' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                    )}>{p.side}</span>
                  </td>
                  <td className="px-4 py-3 text-right mono text-muted">{fmt.num(p.total_shares)}</td>
                  <td className="px-4 py-3 text-right mono">{fmt.pct(p.avg_entry_price)}</td>
                  <td className="px-4 py-3 text-right mono">{fmt.pct(p.current_price)}</td>
                  <td className="px-4 py-3 text-right"><PnlCell value={p.unrealized_pnl} /></td>
                  <td className="px-4 py-3 text-right"><PnlCell value={p.realized_pnl} /></td>
                  <td className="px-5 py-3 text-right text-muted">{fmt.ago(p.opened_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
