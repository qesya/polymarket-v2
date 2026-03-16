import { create } from 'zustand'
import type { MarketCandidate, WSMessage } from '../types/api'

interface WsState {
  connected:        boolean
  liveMarkets:      MarketCandidate[]
  lastTradeAt:      string | null
  lastPortfolioAt:  string | null
  handleMessage:    (msg: WSMessage) => void
}

export const useWsStore = create<WsState>((set) => ({
  connected:       false,
  liveMarkets:     [],
  lastTradeAt:     null,
  lastPortfolioAt: null,

  handleMessage: (msg: WSMessage) => {
    switch (msg.type) {
      case 'market_candidate':
        set(s => {
          const candidate = msg.payload as MarketCandidate
          const existing  = s.liveMarkets.filter(m => m.market_id !== candidate.market_id)
          return { liveMarkets: [candidate, ...existing].slice(0, 200) }
        })
        break

      case 'portfolio_update':
        set({ lastPortfolioAt: msg.ts })
        break

      case 'trade_filled':
        set({ lastTradeAt: msg.ts })
        break

      default:
        break
    }
  },
}))
