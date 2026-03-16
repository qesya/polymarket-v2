export const API_BASE = '/api'
export const WS_URL  = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`

export const CHART = {
  green:  '#22c55e',
  red:    '#ef4444',
  blue:   '#3b82f6',
  amber:  '#f59e0b',
  gray:   '#4b5563',
  purple: '#a855f7',
}

export const REFETCH = {
  overview:         10_000,
  positions:        15_000,
  trades:           20_000,
  markets:          55_000,
  modelPerformance: 300_000,
  riskSummary:      10_000,
  drawdownHistory:  300_000,
}
