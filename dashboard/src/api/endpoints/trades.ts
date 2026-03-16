import { useQuery } from '@tanstack/react-query'
import client from '../client'
import type { TradesResponse } from '../../types/api'
import { REFETCH } from '../../lib/constants'

interface TradeFilters {
  status?: string
  side?:   string
  limit?:  number
  offset?: number
}

export const useTrades = (filters: TradeFilters = {}) =>
  useQuery<TradesResponse>({
    queryKey: ['trades', filters],
    queryFn:  () => client.get('/trades', { params: filters }).then(r => r.data),
    refetchInterval: REFETCH.trades,
  })
