import clsx from 'clsx'

interface Props {
  label:    string
  value:    string
  sub?:     string
  trend?:   'up' | 'down' | 'neutral'
  alert?:   boolean
}

export default function StatCard({ label, value, sub, trend, alert }: Props) {
  return (
    <div className={clsx(
      'bg-card border rounded-xl p-5',
      alert ? 'border-red-500/50' : 'border-border'
    )}>
      <div className="text-xs text-muted uppercase tracking-wide mb-2">{label}</div>
      <div className={clsx(
        'text-2xl font-bold mono',
        alert ? 'text-red-400' :
        trend === 'up' ? 'text-emerald-400' :
        trend === 'down' ? 'text-red-400' : 'text-white'
      )}>
        {value}
      </div>
      {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
    </div>
  )
}
