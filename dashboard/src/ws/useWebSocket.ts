import { useEffect, useRef } from 'react'
import { WS_URL } from '../lib/constants'
import { useWsStore } from './wsStore'
import { queryClient } from '../api/queryClient'
import type { WSMessage } from '../types/api'

let wsInstance: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let backoff = 1000

export function useWebSocket() {
  const mounted = useRef(false)
  const handleMessage = useWsStore(s => s.handleMessage)

  useEffect(() => {
    if (mounted.current) return
    mounted.current = true
    connect(handleMessage)
    return () => {
      wsInstance?.close()
      if (reconnectTimer) clearTimeout(reconnectTimer)
    }
  }, [handleMessage])
}

function connect(handleMessage: (msg: WSMessage) => void) {
  if (wsInstance?.readyState === WebSocket.OPEN) return

  try {
    wsInstance = new WebSocket(WS_URL)
  } catch {
    scheduleReconnect(handleMessage)
    return
  }

  wsInstance.onopen = () => {
    backoff = 1000
    console.log('[WS] connected')
  }

  wsInstance.onmessage = (e) => {
    try {
      const msg: WSMessage = JSON.parse(e.data)
      handleMessage(msg)

      // Invalidate React Query cache on state-changing events
      if (msg.type === 'portfolio_update' || msg.type === 'trade_filled') {
        queryClient.invalidateQueries({ queryKey: ['overview'] })
        queryClient.invalidateQueries({ queryKey: ['positions'] })
      }
      if (msg.type === 'circuit_changed') {
        queryClient.invalidateQueries({ queryKey: ['overview'] })
        queryClient.invalidateQueries({ queryKey: ['risk'] })
      }
      if (msg.type === 'trade_filled') {
        queryClient.invalidateQueries({ queryKey: ['trades'] })
      }
    } catch { /* ignore malformed messages */ }
  }

  wsInstance.onclose = () => {
    console.log('[WS] disconnected — reconnecting in', backoff, 'ms')
    scheduleReconnect(handleMessage)
  }

  wsInstance.onerror = () => wsInstance?.close()
}

function scheduleReconnect(handleMessage: (msg: WSMessage) => void) {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(() => {
    backoff = Math.min(backoff * 2, 30_000)
    connect(handleMessage)
  }, backoff)
}
