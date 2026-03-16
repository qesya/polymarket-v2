import { useQuery } from '@tanstack/react-query'
import client from '../client'
import type { MarketCandidate } from '../../types/api'
import { REFETCH } from '../../lib/constants'

export const useMarkets = () =>
  useQuery<MarketCandidate[]>({
    queryKey: ['markets'],
    queryFn:  () => client.get('/markets/candidates').then(r => r.data),
    refetchInterval: REFETCH.markets,
  })
