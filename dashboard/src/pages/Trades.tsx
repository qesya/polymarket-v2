import { useState } from 'react'
import { useTrades } from '../api/endpoints/trades'
import StatusBadge from '../components/shared/StatusBadge'
import PnlCell from '../components/shared/PnlCell'
import { fmt } from '../lib/formatters'
import clsx from 'clsx'
import type { TradeStatus } from '../types/api'

const STATUSES: TradeStatus[] = ['FILLED', 'PARTIAL', 'PENDING', 'CANCELLED', 'REJECTED']

export default function Trades() {
  const [status, setStatus] = useState<string>('')
  const [side,   setSide]   = useState<string>('')
  const [offset, setOffset] = useState(0)
  const limit = 50

  const { data, isLoading } = useTrades({ status: status || undefined, side: side || undefined, limit, offset })
  const items = data?.items ?? []
  const total = data?.total ?? 0

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Trade History</h1>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <select value={status} onChange={e => { setStatus(e.target.value); setOffset(0) }}
          className="bg-card border border-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent">
          <option value="">All statuses</option>
          {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={side} onChange={e => { setSide(e.target.value); setOffset(0) }}
          className="bg-card border border-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent">
          <option value="">Both sides</option>
          <option value="YES">YES</option>
          <option value="NO">NO</option>
        </select>
        <span className="text-sm text-muted ml-auto">{total} total</span>
      </div>

      <div className="bg-card border border-border rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-10 text-center text-muted text-sm">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted uppercase tracking-wide">
                <th className="text-left px-5 py-3">#</th>
                <th className="text-left px-4 py-3">Market</th>
                <th className="text-center px-3 py-3">Side</th>
                <th className="text-center px-3 py-3">Status</th>
                <th className="text-right px-3 py-3">Size</th>
                <th className="text-right px-3 py-3">Fill Price</th>
                <th className="text-right px-3 py-3">Slippage</th>
                <th className="text-right px-3 py-3">Kelly</th>
                <th className="text-right px-3 py-3">PnL</th>
                <th className="text-right px-5 py-3">Placed</th>
              </tr>
            </thead>
            <tbody>
              {items.map(t => (
                <tr key={t.id} className="border-b border-border/50 hover:bg-white/2 transition-colors">
                  <td className="px-5 py-3 text-muted mono text-xs">{t.id}</td>
                  <td className="px-4 py-3">
                    <div className="max-w-xs truncate" title={t.question}>{t.question}</div>
                    <div className="text-xs text-muted">{t.category}</div>
                  </td>
                  <td className="px-3 py-3 text-center">
                    <span className={clsx('px-2 py-0.5 rounded text-xs font-medium',
                      t.side === 'YES' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                    )}>{t.side}</span>
                  </td>
                  <td className="px-3 py-3 text-center"><StatusBadge status={t.status} /></td>
                  <td className="px-3 py-3 text-right mono">{fmt.usd(t.dollar_size)}</td>
                  <td className="px-3 py-3 text-right mono">{t.fill_price ? fmt.prob(t.fill_price) : '—'}</td>
                  <td className="px-3 py-3 text-right mono text-muted">{t.slippage_bps ? fmt.bps(t.slippage_bps) : '—'}</td>
                  <td className="px-3 py-3 text-right mono text-muted">{fmt.pct(t.kelly_fraction)}</td>
                  <td className="px-3 py-3 text-right"><PnlCell value={t.pnl_realized} /></td>
                  <td className="px-5 py-3 text-right text-muted">{fmt.ago(t.placed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {total > limit && (
        <div className="flex justify-center gap-3">
          <button disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
            className="px-4 py-2 bg-card border border-border rounded-lg text-sm disabled:opacity-40 hover:border-accent transition-colors">
            ← Previous
          </button>
          <span className="px-4 py-2 text-sm text-muted">
            {offset + 1}–{Math.min(offset + limit, total)} of {total}
          </span>
          <button disabled={offset + limit >= total}
            onClick={() => setOffset(offset + limit)}
            className="px-4 py-2 bg-card border border-border rounded-lg text-sm disabled:opacity-40 hover:border-accent transition-colors">
            Next →
          </button>
        </div>
      )}
    </div>
  )
}
