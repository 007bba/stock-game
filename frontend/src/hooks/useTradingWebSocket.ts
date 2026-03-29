import { useEffect } from 'react'
import { message } from 'antd'
import type { OrderItem } from '../components/OrderList'
import { toUiOrder, type ApiOrder } from '../services/tradingApi'
import { WebSocketClient, createSeasonSocketUrl, type SocketMessage } from '../services/websocket'
import { useAuthStore } from '../stores/authStore'
import { useTradingStore } from '../stores/tradingStore'

interface UseTradingWebSocketOptions {
  enabled: boolean
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isApiOrder(value: unknown): value is ApiOrder {
  if (!isObject(value)) {
    return false
  }

  return (
    typeof value.id === 'number' &&
    typeof value.tsCode === 'string' &&
    typeof value.side === 'string' &&
    typeof value.limitPrice === 'number' &&
    typeof value.quantity === 'number' &&
    typeof value.remainingQty === 'number' &&
    typeof value.status === 'string' &&
    typeof value.createdAt === 'string'
  )
}

function toRejectedOrder(payload: Record<string, unknown>): OrderItem | null {
  const orderId = payload.orderId
  if (typeof orderId !== 'number' && typeof orderId !== 'string') {
    return null
  }

  const tsCode = typeof payload.tsCode === 'string' ? payload.tsCode : 'UNKNOWN'
  const sideRaw = typeof payload.side === 'string' ? payload.side : 'buy'
  const qty = typeof payload.quantity === 'number' ? payload.quantity : 0
  const price = typeof payload.limitPrice === 'number' ? payload.limitPrice : 0

  return {
    orderId: String(orderId),
    tsCode,
    side: sideRaw.toLowerCase() === 'sell' ? 'SELL' : 'BUY',
    qty,
    price,
    status: 'REJECTED',
  }
}

function applySocketMessage(messageEnvelope: SocketMessage, seasonId: number): void {
  const store = useTradingStore.getState()
  if (!store.acceptWsSequence(messageEnvelope.sequence)) {
    return
  }

  const payload = isObject(messageEnvelope.payload) ? messageEnvelope.payload : null
  if (!payload) {
    return
  }

  const payloadSeasonId = payload.seasonId
  if (typeof payloadSeasonId === 'number' && payloadSeasonId !== seasonId) {
    return
  }

  if (messageEnvelope.event === 'order_updated' || messageEnvelope.event === 'order_matched') {
    const rawOrder = payload.order
    if (!isApiOrder(rawOrder)) {
      return
    }
    store.upsertOrder(toUiOrder(rawOrder))
    return
  }

  if (messageEnvelope.event === 'order_rejected') {
    const orderId = payload.orderId
    if (typeof orderId === 'number' || typeof orderId === 'string') {
      const currentOrder = store.orders.find((item) => item.orderId === String(orderId))
      if (currentOrder) {
        store.upsertOrder({
          ...currentOrder,
          status: 'REJECTED',
        })
        return
      }
    }

    const fallbackRejectedOrder = toRejectedOrder(payload)
    if (fallbackRejectedOrder) {
      store.upsertOrder(fallbackRejectedOrder)
    }
    return
  }

  if (messageEnvelope.event === 'position_update') {
    const tsCode = payload.tsCode
    const qtyTotal = payload.qtyTotal
    const avgCost = payload.avgCost
    if (typeof tsCode === 'string' && typeof qtyTotal === 'number' && typeof avgCost === 'number') {
      store.upsertPosition({
        tsCode,
        qty: qtyTotal,
        avgPrice: avgCost,
      })
    }
    return
  }

  if (messageEnvelope.event === 'account_update') {
    const availableCash = payload.availableCash
    if (typeof availableCash === 'number') {
      store.setAvailableCash(availableCash)
    }
  }
}

export function useTradingWebSocket(options: UseTradingWebSocketOptions): void {
  const token = useAuthStore((state) => state.session?.access_token ?? null)
  const seasonId = useTradingStore((state) => state.currentSeasonId)
  const setWsConnected = useTradingStore((state) => state.setWsConnected)
  const setWsReconnectAttempts = useTradingStore((state) => state.setWsReconnectAttempts)

  useEffect(() => {
    if (!options.enabled || !token || seasonId === null) {
      setWsConnected(false)
      setWsReconnectAttempts(0)
      return
    }

    const wsUrl = createSeasonSocketUrl({ seasonId, token })
    const wsClient = new WebSocketClient(wsUrl, {
      onOpen: () => {
        setWsConnected(true)
        setWsReconnectAttempts(0)
      },
      onClose: () => {
        setWsConnected(false)
      },
      onReconnectAttempt: (attempt) => {
        setWsReconnectAttempts(attempt)
      },
      onReconnectExhausted: (maxAttempts) => {
        setWsConnected(false)
        setWsReconnectAttempts(maxAttempts)
        message.error(`实时连接已断开，重连失败（${maxAttempts} 次）`)
      },
      onMessage: (nextMessage) => {
        applySocketMessage(nextMessage, seasonId)
      },
    })

    wsClient.connect()

    return () => {
      wsClient.disconnect()
      setWsConnected(false)
    }
  }, [options.enabled, seasonId, setWsConnected, setWsReconnectAttempts, token])
}
