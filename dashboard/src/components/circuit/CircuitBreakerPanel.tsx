import clsx from 'clsx'
import { ShieldCheck, ShieldX } from 'lucide-react'
import type { CircuitBreaker, CircuitName } from '../../types/api'
import { fmt } from '../../lib/formatters'

interface Props {
  breakers: Record<CircuitName, CircuitBreaker>
}

const LABELS: Record<CircuitName, string> = {
  api:       'Polymarket API',
  trading:   'Trading',
  model:     'ML Model',
  execution: 'Execution',
}

export default function CircuitBreakerPanel({ breakers }: Props) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {(Object.keys(LABELS) as CircuitName[]).map(name => {
        const cb = breakers[name]
        const open = cb?.is_open ?? false
        return (
          <div key={name} className={clsx(
            'bg-card border rounded-xl p-4 flex items-start gap-3',
            open ? 'border-red-500/50' : 'border-border'
          )}>
            {open
              ? <ShieldX size={20} className="text-red-400 flex-shrink-0 mt-0.5" />
              : <ShieldCheck size={20} className="text-emerald-400 flex-shrink-0 mt-0.5" />
            }
            <div className="min-w-0">
              <div className="text-sm font-medium">{LABELS[name]}</div>
              <div className={clsx('text-xs mt-0.5', open ? 'text-red-400' : 'text-muted')}>
                {open ? 'OPEN' : 'CLOSED'}
              </div>
              {open && cb?.reason && (
                <div className="text-xs text-muted mt-1 truncate" title={cb.reason}>{cb.reason}</div>
              )}
              {open && cb?.opened_at && (
                <div className="text-xs text-muted mt-0.5">{fmt.ago(cb.opened_at)}</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
