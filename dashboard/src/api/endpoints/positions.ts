import { useQuery } from '@tanstack/react-query'
import client from '../client'
import type { Position } from '../../types/api'
import { REFETCH } from '../../lib/constants'

export const usePositions = () =>
  useQuery<Position[]>({
    queryKey: ['positions'],
    queryFn:  () => client.get('/positions').then(r => r.data),
    refetchInterval: REFETCH.positions,
  })
