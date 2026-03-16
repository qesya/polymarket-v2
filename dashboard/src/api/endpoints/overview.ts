import { useQuery } from '@tanstack/react-query'
import client from '../client'
import type { Overview } from '../../types/api'
import { REFETCH } from '../../lib/constants'

export const useOverview = () =>
  useQuery<Overview>({
    queryKey: ['overview'],
    queryFn:  () => client.get('/overview').then(r => r.data),
    refetchInterval: REFETCH.overview,
  })
