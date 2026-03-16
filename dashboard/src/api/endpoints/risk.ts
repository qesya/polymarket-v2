import { useQuery } from '@tanstack/react-query'
import client from '../client'
import type { RiskSummary, DrawdownPoint } from '../../types/api'
import { REFETCH } from '../../lib/constants'

export const useRiskSummary = () =>
  useQuery<RiskSummary>({
    queryKey: ['risk'],
    queryFn:  () => client.get('/risk/summary').then(r => r.data),
    refetchInterval: REFETCH.riskSummary,
  })

export const useDrawdownHistory = (days = 30) =>
  useQuery<DrawdownPoint[]>({
    queryKey: ['drawdown', days],
    queryFn:  () => client.get('/risk/drawdown-history', { params: { days } }).then(r => r.data),
    refetchInterval: REFETCH.drawdownHistory,
  })
