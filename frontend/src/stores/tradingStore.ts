import { create } from 'zustand'
import type { OrderItem } from '../components/OrderList'
import type { PositionItem } from '../components/PositionList'

export type OrderSide = 'BUY' | 'SELL'

export interface OrderDraft {
  side: OrderSide
  price: number | null
  qty: number | null
}

interface TradingState {
  currentSeasonId: number | null
  currentAccountId: number | null
  selectedSymbol: string
  orderDraft: OrderDraft
  availableCash: number
  positions: PositionItem[]
  orders: OrderItem[]
  wsConnected: boolean
  wsReconnectAttempts: number
  lastWsSequence: number
  setCurrentSeason: (seasonId: number | null) => void
  setCurrentAccount: (accountId: number | null) => void
  setSelectedSymbol: (symbol: string) => void
  updateOrderDraft: (patch: Partial<OrderDraft>) => void
  resetOrderDraft: () => void
  setAvailableCash: (availableCash: number) => void
  setPositions: (positions: PositionItem[]) => void
  setOrders: (orders: OrderItem[]) => void
  prependOrder: (order: OrderItem) => void
  upsertOrder: (order: OrderItem) => void
  upsertPosition: (position: Pick<PositionItem, 'tsCode' | 'qty' | 'avgPrice'>) => void
  setWsConnected: (connected: boolean) => void
  setWsReconnectAttempts: (attempts: number) => void
  acceptWsSequence: (sequence: number | undefined) => boolean
  resetRealtimeState: () => void
}

const defaultDraft: OrderDraft = {
  side: 'BUY',
  price: null,
  qty: null,
}

const defaultPositions: PositionItem[] = [
  { tsCode: '600000.SH', qty: 1000, avgPrice: 10.21 },
  { tsCode: '000001.SZ', qty: 500, avgPrice: 12.05 },
  { tsCode: '600519.SH', qty: 100, avgPrice: 1698.0 },
]

const defaultOrders: OrderItem[] = [
  {
    orderId: 'MOCK-INIT-1',
    tsCode: '600000.SH',
    side: 'BUY',
    qty: 1000,
    price: 10.21,
    status: 'FILLED',
  },
  {
    orderId: 'MOCK-INIT-2',
    tsCode: '000001.SZ',
    side: 'BUY',
    qty: 500,
    price: 12.05,
    status: 'PARTIAL',
  },
]

const MAX_ORDERS = 30

export const useTradingStore = create<TradingState>((set) => ({
  currentSeasonId: null,
  currentAccountId: null,
  selectedSymbol: '000001.SZ',
  orderDraft: defaultDraft,
  availableCash: 1000000,
  positions: defaultPositions,
  orders: defaultOrders,
  wsConnected: false,
  wsReconnectAttempts: 0,
  lastWsSequence: 0,

  setCurrentSeason: (seasonId) => {
    set({ currentSeasonId: seasonId })
  },

  setCurrentAccount: (accountId) => {
    set({ currentAccountId: accountId })
  },

  setSelectedSymbol: (symbol) => {
    set({ selectedSymbol: symbol })
  },

  updateOrderDraft: (patch) => {
    set((state) => ({
      orderDraft: {
        ...state.orderDraft,
        ...patch,
      },
    }))
  },

  resetOrderDraft: () => {
    set({ orderDraft: defaultDraft })
  },

  setAvailableCash: (availableCash) => {
    set({ availableCash })
  },

  setPositions: (positions) => {
    set({ positions })
  },

  setOrders: (orders) => {
    set({ orders: orders.slice(0, MAX_ORDERS) })
  },

  prependOrder: (order) => {
    set((state) => ({
      orders: [order, ...state.orders.filter((item) => item.orderId !== order.orderId)].slice(0, MAX_ORDERS),
    }))
  },

  upsertOrder: (order) => {
    set((state) => {
      const index = state.orders.findIndex((item) => item.orderId === order.orderId)
      if (index < 0) {
        return {
          orders: [order, ...state.orders].slice(0, MAX_ORDERS),
        }
      }

      const nextOrders = [...state.orders]
      nextOrders[index] = order
      return { orders: nextOrders }
    })
  },

  upsertPosition: (position) => {
    set((state) => {
      const filtered = state.positions.filter((item) => item.tsCode !== position.tsCode)
      if (position.qty <= 0) {
        return { positions: filtered }
      }

      return {
        positions: [...filtered, { ...position }],
      }
    })
  },

  setWsConnected: (connected) => {
    set({ wsConnected: connected })
  },

  setWsReconnectAttempts: (attempts) => {
    set({ wsReconnectAttempts: Math.max(0, attempts) })
  },

  acceptWsSequence: (sequence) => {
    if (sequence === undefined || !Number.isFinite(sequence)) {
      return true
    }

    let accepted = false
    set((state) => {
      if (sequence <= state.lastWsSequence) {
        return state
      }
      accepted = true
      return { lastWsSequence: sequence }
    })
    return accepted
  },

  resetRealtimeState: () => {
    set({
      availableCash: 1000000,
      positions: defaultPositions,
      orders: defaultOrders,
      wsConnected: false,
      wsReconnectAttempts: 0,
      lastWsSequence: 0,
    })
  },
}))
