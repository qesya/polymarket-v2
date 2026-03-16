export type TradeSide   = 'YES' | 'NO'
export type TradeStatus = 'PENDING' | 'FILLED' | 'PARTIAL' | 'CANCELLED' | 'REJECTED'
export type CircuitName = 'api' | 'trading' | 'model' | 'execution'
export type MarketCategory = 'politics' | 'sports' | 'crypto' | 'finance' | 'science' | 'entertainment' | 'other'

export interface CircuitBreaker {
  name: CircuitName
  is_open: boolean
  reason: string
  opened_at: string | null
}

export interface AgentHealth {
  avg_cycle_seconds: number
  error_count: number
  healthy: boolean
}

export interface Overview {
  portfolio_value:      number
  cash_available:       number
  daily_pnl:            number
  peak_value:           number
  current_drawdown_pct: number
  open_position_count:  number
  win_rate_30d:         number
  total_trades_30d:     number
  total_pnl_30d:        number
  circuit_breakers: Record<CircuitName, CircuitBreaker>
  agent_health:     Record<string, AgentHealth>
}

export interface Position {
  market_id:      string
  question:       string
  category:       MarketCategory
  side:           TradeSide
  total_shares:   number
  avg_entry_price: number
  current_price:  number
  unrealized_pnl: number
  realized_pnl:   number
  opened_at:      string
  updated_at:     string
}

export interface Trade {
  id:              number
  market_id:       string
  question:        string
  category:        MarketCategory
  side:            TradeSide
  status:          TradeStatus
  dollar_size:     number
  fill_price:      number | null
  intended_price:  number
  slippage_bps:    number | null
  filled_shares:   number
  pnl_realized:    number | null
  kelly_fraction:  number
  placed_at:       string
  filled_at:       string | null
}

export interface TradesResponse {
  items:  Trade[]
  total:  number
  limit:  number
  offset: number
}

export interface MarketCandidate {
  market_id:         string
  question:          string
  category:          MarketCategory
  price_yes:         number
  volume_24h:        number
  liquidity?:        number
  bid_ask_spread?:   number
  time_to_resolution_hours?: number
  volatility_7d?:    number
  opportunity_score: number
  scanned_at?:       string
}

export interface EnsembleWeights {
  xgb:    number
  lgbm:   number
  claude: number
}

export interface CalibrationPoint {
  predicted_bucket: number
  actual_rate:      number
  count:            number
}

export interface AccuracyPoint {
  date:        string
  accuracy:    number
  predictions: number
}

export interface ModelVersion {
  version:          string
  deployed_at:      string
  xgb_brier_score:  number
  lgbm_brier_score: number
  training_samples: number
}

export interface ModelPerformance {
  current_version:  string
  xgb_brier_score:  number
  lgbm_brier_score: number
  training_samples: number
  deployed_at:      string | null
  weights:          EnsembleWeights
  calibration:      CalibrationPoint[]
  accuracy_history: AccuracyPoint[]
  version_history:  ModelVersion[]
}

export interface RejectionReason {
  reason: string
  count:  number
}

export interface RiskSummary {
  current_drawdown_pct:   number
  max_drawdown_pct:       number
  daily_pnl:              number
  daily_loss_limit_pct:   number
  kelly_fraction:         number
  max_open_positions:     number
  current_open_positions: number
  circuit_breakers:       Record<CircuitName, CircuitBreaker>
  rejection_reasons:      RejectionReason[]
}

export interface DrawdownPoint {
  date:                string
  portfolio_value_eod: number
  pnl:                 number
  drawdown_pct:        number
}

// WebSocket message types
export type WSMessageType =
  | 'portfolio_update'
  | 'trade_filled'
  | 'circuit_changed'
  | 'market_candidate'
  | 'prediction_result'
  | 'agent_heartbeat'

export interface WSMessage {
  type:    WSMessageType
  topic:   string
  payload: unknown
  ts:      string
}
