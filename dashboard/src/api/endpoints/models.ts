import { useQuery } from '@tanstack/react-query'
import client from '../client'
import type { ModelPerformance } from '../../types/api'
import { REFETCH } from '../../lib/constants'

export const useModelPerformance = () =>
  useQuery<ModelPerformance>({
    queryKey: ['models'],
    queryFn:  () => client.get('/models/performance').then(r => r.data),
    refetchInterval: REFETCH.modelPerformance,
  })
