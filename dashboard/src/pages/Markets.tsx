import { useMarkets } from '../api/endpoints/markets'
import { useWsStore } from '../ws/wsStore'
import { fmt } from '../lib/formatters'
import clsx from 'clsx'

export default function Markets() {
  const { data: httpMarkets = [] } = useMarkets()
  const wsMarkets = useWsStore(s => s.liveMarkets)

  // Prefer live WS feed, fall back to HTTP
  const markets = wsMarkets.length > 0 ? wsMarkets : httpMarkets

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Market Scanner</h1>
        <div className="flex items-center gap-2 text-sm text-muted">
          {wsMarkets.length > 0 && (
            <><span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse inline-block" /> Live</>
          )}
          <span>· {markets.length} candidates</span>
        </div>
      </div>

      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs text-muted uppercase tracking-wide">
              <th className="text-left px-5 py-3">Market</th>
              <th className="text-center px-3 py-3">Cat</th>
              <th className="text-right px-3 py-3">YES Price</th>
              <th className="text-right px-3 py-3">Volume 24h</th>
              <th className="text-right px-3 py-3">Spread</th>
              <th className="text-right px-3 py-3">TTR</th>
              <th className="text-right px-3 py-3">Volatility</th>
              <th className="px-5 py-3">Opportunity</th>
            </tr>
          </thead>
          <tbody>
            {markets.map(m => (
              <tr key={m.market_id} className="border-b border-border/50 hover:bg-white/2 transition-colors">
                <td className="px-5 py-3">
                  <div className="max-w-sm truncate font-medium" title={m.question}>{m.question}</div>
                </td>
                <td className="px-3 py-3 text-center">
                  <span className="text-xs text-muted uppercase">{m.category}</span>
                </td>
                <td className="px-3 py-3 text-right mono font-medium">{fmt.prob(m.price_yes)}</td>
                <td className="px-3 py-3 text-right mono text-muted">{fmt.usd(m.volume_24h)}</td>
                <td className="px-3 py-3 text-right mono text-muted">
                  {m.bid_ask_spread ? fmt.prob(m.bid_ask_spread) : '—'}
                </td>
                <td className="px-3 py-3 text-right mono text-muted">
                  {m.time_to_resolution_hours ? `${m.time_to_resolution_hours.toFixed(0)}h` : '—'}
                </td>
                <td className="px-3 py-3 text-right mono text-muted">
                  {m.volatility_7d ? fmt.prob(m.volatility_7d) : '—'}
                </td>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 bg-border rounded-full h-1.5">
                      <div
                        className={clsx('h-1.5 rounded-full', m.opportunity_score > 0.7 ? 'bg-emerald-500' : m.opportunity_score > 0.4 ? 'bg-accent' : 'bg-muted')}
                        style={{ width: `${Math.min(m.opportunity_score * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs mono text-muted w-8 text-right">
                      {(m.opportunity_score * 100).toFixed(0)}
                    </span>
                  </div>
                </td>
              </tr>
            ))}
            {markets.length === 0 && (
              <tr><td colSpan={8} className="px-5 py-10 text-center text-muted text-sm">Waiting for scanner…</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
