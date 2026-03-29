import { create } from 'zustand'

export interface MarketTick {
  tsCode: string
  lastPrice: number
  changePct: number
  volume: number
  updatedAt: string
}

interface MarketState {
  ticksByCode: Record<string, MarketTick>
  upsertTick: (tick: MarketTick) => void
  upsertTicks: (ticks: MarketTick[]) => void
  clearTicks: () => void
}

export const useMarketStore = create<MarketState>((set) => ({
  ticksByCode: {},

  upsertTick: (tick) => {
    set((state) => ({
      ticksByCode: {
        ...state.ticksByCode,
        [tick.tsCode]: tick,
      },
    }))
  },

  upsertTicks: (ticks) => {
    set((state) => {
      const next = { ...state.ticksByCode }
      for (const tick of ticks) {
        next[tick.tsCode] = tick
      }
      return { ticksByCode: next }
    })
  },

  clearTicks: () => {
    set({ ticksByCode: {} })
  },
}))
