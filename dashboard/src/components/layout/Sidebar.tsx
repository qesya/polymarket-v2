import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Briefcase, ArrowLeftRight, BarChart2, Brain, ShieldAlert } from 'lucide-react'
import clsx from 'clsx'

const NAV = [
  { to: '/overview',  label: 'Overview',   icon: LayoutDashboard },
  { to: '/positions', label: 'Positions',  icon: Briefcase },
  { to: '/trades',    label: 'Trades',     icon: ArrowLeftRight },
  { to: '/markets',   label: 'Markets',    icon: BarChart2 },
  { to: '/models',    label: 'Models',     icon: Brain },
  { to: '/risk',      label: 'Risk',       icon: ShieldAlert },
]

export default function Sidebar() {
  return (
    <aside className="w-56 flex-shrink-0 bg-card border-r border-border flex flex-col">
      <div className="p-5 border-b border-border">
        <div className="text-sm font-bold text-white tracking-wider uppercase">Polymarket AI</div>
        <div className="text-xs text-muted mt-0.5">Trading System</div>
      </div>

      <nav className="flex-1 p-3 space-y-1">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors',
                isActive
                  ? 'bg-accent/20 text-accent font-medium'
                  : 'text-muted hover:text-white hover:bg-white/5'
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="p-4 border-t border-border text-xs text-muted">
        v1.0.0 · <a href="http://localhost:3000" target="_blank" rel="noreferrer" className="hover:text-white">Grafana ↗</a>
      </div>
    </aside>
  )
}
