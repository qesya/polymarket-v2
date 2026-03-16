import clsx from 'clsx'
import type { TradeStatus } from '../../types/api'

const MAP: Record<TradeStatus, string> = {
  FILLED:    'bg-emerald-500/20 text-emerald-400',
  PARTIAL:   'bg-amber-500/20 text-amber-400',
  PENDING:   'bg-blue-500/20 text-blue-400',
  CANCELLED: 'bg-gray-500/20 text-gray-400',
  REJECTED:  'bg-red-500/20 text-red-400',
}

export default function StatusBadge({ status }: { status: TradeStatus }) {
  return (
    <span className={clsx('px-2 py-0.5 rounded text-xs font-medium', MAP[status] ?? 'bg-gray-500/20 text-gray-400')}>
      {status}
    </span>
  )
}
