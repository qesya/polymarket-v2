export const fmt = {
  usd: (v: number) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(v),

  pct: (v: number, decimals = 1) => `${(v * 100).toFixed(decimals)}%`,

  bps: (v: number) => `${v.toFixed(1)} bps`,

  num: (v: number) =>
    new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(v),

  date: (v: string | null) =>
    v ? new Date(v).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—',

  ago: (v: string | null) => {
    if (!v) return '—'
    const diff = Date.now() - new Date(v).getTime()
    const s = Math.floor(diff / 1000)
    if (s < 60) return `${s}s ago`
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}m ago`
    return `${Math.floor(m / 60)}h ago`
  },

  prob: (v: number) => `${(v * 100).toFixed(1)}%`,

  brier: (v: number) => v.toFixed(4),
}
