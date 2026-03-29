import { create } from 'zustand'

export type OrderSide = 'BUY' | 'SELL'

export interface OrderDraft {
  side: OrderSide
  price: number | null
  qty: number | null
}

interface TradingState {
  currentSeasonId: number | null
  selectedSymbol: string
  orderDraft: OrderDraft
  setCurrentSeason: (seasonId: number | null) => void
  setSelectedSymbol: (symbol: string) => void
  updateOrderDraft: (patch: Partial<OrderDraft>) => void
  resetOrderDraft: () => void
}

const defaultDraft: OrderDraft = {
  side: 'BUY',
  price: null,
  qty: null,
}

export const useTradingStore = create<TradingState>((set) => ({
  currentSeasonId: null,
  selectedSymbol: '000001.SZ',
  orderDraft: defaultDraft,

  setCurrentSeason: (seasonId) => {
    set({ currentSeasonId: seasonId })
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
}))
