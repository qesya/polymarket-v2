import clsx from 'clsx'
import { fmt } from '../../lib/formatters'

export default function PnlCell({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="text-muted">—</span>
  return (
    <span className={clsx('mono', value > 0 ? 'pnl-pos' : value < 0 ? 'pnl-neg' : 'pnl-zero')}>
      {value > 0 ? '+' : ''}{fmt.usd(value)}
    </span>
  )
}
