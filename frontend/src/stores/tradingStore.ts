import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { OrderItem, OrderStatus } from '../components/OrderList'
import type { PositionItem } from '../components/PositionList'
import { getMockLastPrice } from '../services/mockTrading'

export type OrderSide = 'BUY' | 'SELL'

export interface OrderDraft {
  side: OrderSide
  price: number | null
  qty: number | null
}

export interface TickMeta {
  tickId: number
  seasonId: number
  gameDayNo: number
  minuteOfDay: number
  phase: string
  matchingMode: string
  isTradable: boolean
  isMatchingPoint: boolean
  nextTickId?: number | null
  nextTickAt?: string | null
}

export interface ReplayQuote {
  tsCode: string
  refPrice: number
  openPrice: number | null
  highPrice: number | null
  lowPrice: number | null
  closePrice: number | null
  vwapPrice: number | null
  volume: number
  upperLimitPrice: number
  lowerLimitPrice: number
  isHalted: boolean
  pctChange: number
  isLimitUp: boolean
  isLimitDown: boolean
  auctionImbalanceRatio?: number | null
  auctionHintLevel?: number
}

export interface ReplayCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
}

export interface SymbolReplayState {
  quote: ReplayQuote
  candles: ReplayCandle[]
}

export interface TrainingSession {
  sessionId: string
  presetId: string
  title: string
  focus: string
  description: string
  symbolUniverse: string[]
  defaultSymbol: string
  dateRange: string
  startingCash: number
  datasetSeasonId: number | null
  startedAt: string
  completedAt: string | null
}

export interface TrainingSessionSeed {
  presetId: string
  title: string
  focus: string
  description: string
  symbolUniverse: string[]
  defaultSymbol: string
  dateRange: string
  startingCash: number
  datasetSeasonId: number | null
}

export interface TradeNote {
  noteId: string
  orderId: string
  symbol: string
  side: OrderSide
  price: number
  qty: number
  content: string
  tickId: number | null
  orderStatus: OrderStatus
  createdAt: string
}

export interface TrainingReviewSummary {
  sessionId: string
  title: string
  focus: string
  startedAt: string
  completedAt: string
  totalAsset: number
  availableCash: number
  holdingValue: number
  netPnl: number
  returnPct: number
  totalOrders: number
  executedOrders: number
  rejectedOrders: number
  winRate: number
  noteCoverage: number
  disciplineScore: number
  notes: TradeNote[]
  orders: OrderItem[]
  positions: PositionItem[]
}

interface TradingState {
  currentSeasonId: number | null
  currentAccountId: number | null
  currentTrainingSession: TrainingSession | null
  trainingNotes: TradeNote[]
  reviewSummary: TrainingReviewSummary | null
  selectedSymbol: string
  orderDraft: OrderDraft
  availableCash: number
  positions: PositionItem[]
  orders: OrderItem[]
  wsConnected: boolean
  wsReconnectAttempts: number
  lastWsSequence: number
  currentTick: TickMeta | null
  marketBySymbol: Record<string, SymbolReplayState>
  setCurrentSeason: (seasonId: number | null) => void
  setCurrentAccount: (accountId: number | null) => void
  startTrainingSession: (seed: TrainingSessionSeed) => void
  clearTrainingSession: () => void
  setSelectedSymbol: (symbol: string) => void
  updateOrderDraft: (patch: Partial<OrderDraft>) => void
  resetOrderDraft: () => void
  setAvailableCash: (availableCash: number) => void
  setPositions: (positions: PositionItem[]) => void
  setOrders: (orders: OrderItem[]) => void
  prependOrder: (order: OrderItem) => void
  upsertOrder: (order: OrderItem) => void
  upsertPosition: (position: Pick<PositionItem, 'tsCode' | 'qty' | 'avgPrice'>) => void
  recordTradeNote: (note: Omit<TradeNote, 'noteId' | 'createdAt'>) => void
  clearReviewSummary: () => void
  finishTrainingSession: () => TrainingReviewSummary | null
  setWsConnected: (connected: boolean) => void
  setWsReconnectAttempts: (attempts: number) => void
  setCurrentTick: (tick: TickMeta | null) => void
  applyTickQuotes: (tickId: number, quotes: ReplayQuote[], isMatchingPoint?: boolean) => void
  acceptWsSequence: (sequence: number | undefined) => boolean
  resetRealtimeState: () => void
}

const defaultDraft: OrderDraft = {
  side: 'BUY',
  price: null,
  qty: null,
}

const defaultPositions: PositionItem[] = []
const defaultOrders: OrderItem[] = []

const MAX_ORDERS = 30
const MAX_REPLAY_CANDLES = 240

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function createSessionId(prefix: string): string {
  return `${prefix}-${Date.now()}`
}

function toReplayCandle(tickId: number, quote: ReplayQuote): ReplayCandle {
  const open = quote.openPrice ?? quote.refPrice
  const close = quote.closePrice ?? quote.refPrice
  const high = quote.highPrice ?? Math.max(open, close)
  const low = quote.lowPrice ?? Math.min(open, close)

  return {
    time: tickId,
    open,
    high,
    low,
    close,
  }
}

function mergeNonMatchingCandle(current: ReplayCandle, incoming: ReplayCandle): ReplayCandle {
  return {
    ...current,
    high: Math.max(current.high, incoming.high, incoming.close),
    low: Math.min(current.low, incoming.low, incoming.close),
    close: incoming.close,
  }
}

function buildReviewSummary(state: {
  currentTrainingSession: TrainingSession | null
  trainingNotes: TradeNote[]
  orders: OrderItem[]
  positions: PositionItem[]
  availableCash: number
  marketBySymbol: Record<string, SymbolReplayState>
}): TrainingReviewSummary | null {
  const session = state.currentTrainingSession
  if (!session) {
    return null
  }

  const holdingValue = round2(
    state.positions.reduce((sum, item) => {
      const markPrice = state.marketBySymbol[item.tsCode]?.quote.refPrice ?? getMockLastPrice(item.tsCode)
      return sum + item.qty * markPrice
    }, 0),
  )
  const totalAsset = round2(state.availableCash + holdingValue)
  const netPnl = round2(totalAsset - session.startingCash)
  const returnPct = session.startingCash > 0 ? round2((netPnl / session.startingCash) * 100) : 0
  const executedOrders = state.orders.filter((item) => item.status === 'FILLED' || item.status === 'PARTIAL')
  const rejectedOrders = state.orders.filter((item) => item.status === 'REJECTED').length

  const wins = executedOrders.filter((item) => {
    const currentPrice = state.marketBySymbol[item.tsCode]?.quote.refPrice ?? getMockLastPrice(item.tsCode)
    return item.side === 'BUY' ? currentPrice >= item.price : currentPrice <= item.price
  }).length
  const winRate = executedOrders.length > 0 ? round2((wins / executedOrders.length) * 100) : 0

  const noteCoverage = state.orders.length > 0 ? round2((state.trainingNotes.length / state.orders.length) * 100) : 100
  const overtradePenalty = Math.max(0, state.orders.length - 8) * 4
  const missingNotePenalty = Math.max(0, 100 - noteCoverage) * 0.35
  const rejectPenalty = rejectedOrders * 8
  const disciplineScore = clamp(Math.round(100 - overtradePenalty - missingNotePenalty - rejectPenalty), 0, 100)

  return {
    sessionId: session.sessionId,
    title: session.title,
    focus: session.focus,
    startedAt: session.startedAt,
    completedAt: new Date().toISOString(),
    totalAsset,
    availableCash: round2(state.availableCash),
    holdingValue,
    netPnl,
    returnPct,
    totalOrders: state.orders.length,
    executedOrders: executedOrders.length,
    rejectedOrders,
    winRate,
    noteCoverage,
    disciplineScore,
    notes: [...state.trainingNotes],
    orders: [...state.orders],
    positions: [...state.positions],
  }
}

export const useTradingStore = create<TradingState>()(
  persist(
    (set, get) => ({
      currentSeasonId: null,
      currentAccountId: null,
      currentTrainingSession: null,
      trainingNotes: [],
      reviewSummary: null,
      selectedSymbol: '000001.SZ',
      orderDraft: defaultDraft,
      availableCash: 1000000,
      positions: defaultPositions,
      orders: defaultOrders,
      wsConnected: false,
      wsReconnectAttempts: 0,
      lastWsSequence: 0,
      currentTick: null,
      marketBySymbol: {},

      setCurrentSeason: (seasonId) => {
        set({ currentSeasonId: seasonId })
      },

      setCurrentAccount: (accountId) => {
        set({ currentAccountId: accountId })
      },

      startTrainingSession: (seed) => {
        set({
          currentTrainingSession: {
            sessionId: createSessionId(seed.presetId),
            presetId: seed.presetId,
            title: seed.title,
            focus: seed.focus,
            description: seed.description,
            symbolUniverse: [...seed.symbolUniverse],
            defaultSymbol: seed.defaultSymbol,
            dateRange: seed.dateRange,
            startingCash: seed.startingCash,
            datasetSeasonId: seed.datasetSeasonId,
            startedAt: new Date().toISOString(),
            completedAt: null,
          },
          currentSeasonId: seed.datasetSeasonId,
          currentAccountId: null,
          reviewSummary: null,
          trainingNotes: [],
          selectedSymbol: seed.defaultSymbol,
          orderDraft: defaultDraft,
          availableCash: seed.startingCash,
          positions: defaultPositions,
          orders: defaultOrders,
          wsConnected: false,
          wsReconnectAttempts: 0,
          lastWsSequence: 0,
          currentTick: null,
          marketBySymbol: {},
        })
      },

      clearTrainingSession: () => {
        set({
          currentSeasonId: null,
          currentAccountId: null,
          currentTrainingSession: null,
          trainingNotes: [],
          reviewSummary: null,
          selectedSymbol: '000001.SZ',
          orderDraft: defaultDraft,
          availableCash: 1000000,
          positions: defaultPositions,
          orders: defaultOrders,
          wsConnected: false,
          wsReconnectAttempts: 0,
          lastWsSequence: 0,
          currentTick: null,
          marketBySymbol: {},
        })
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

      recordTradeNote: (note) => {
        set((state) => ({
          trainingNotes: [
            {
              ...note,
              noteId: createSessionId('note'),
              createdAt: new Date().toISOString(),
            },
            ...state.trainingNotes,
          ].slice(0, MAX_ORDERS),
        }))
      },

      clearReviewSummary: () => {
        set({ reviewSummary: null })
      },

      finishTrainingSession: () => {
        const summary = buildReviewSummary(get())
        if (summary === null) {
          return null
        }

        set((state) => ({
          reviewSummary: summary,
          currentTrainingSession: state.currentTrainingSession
            ? {
                ...state.currentTrainingSession,
                completedAt: summary.completedAt,
              }
            : null,
        }))

        return summary
      },

      setWsConnected: (connected) => {
        set({ wsConnected: connected })
      },

      setWsReconnectAttempts: (attempts) => {
        set({ wsReconnectAttempts: Math.max(0, attempts) })
      },

      setCurrentTick: (tick) => {
        set({ currentTick: tick })
      },

      applyTickQuotes: (tickId, quotes, isMatchingPoint = false) => {
        set((state) => {
          const nextMarketBySymbol = { ...state.marketBySymbol }

          for (const quote of quotes) {
            const prev = nextMarketBySymbol[quote.tsCode]
            const nextCandle = toReplayCandle(tickId, quote)
            const nextCandles = prev ? [...prev.candles] : []

            if (nextCandles.length === 0) {
              nextCandles.push(nextCandle)
            } else if (isMatchingPoint) {
              if (nextCandles[nextCandles.length - 1].time === tickId) {
                nextCandles[nextCandles.length - 1] = nextCandle
              } else {
                nextCandles.push(nextCandle)
              }
            } else {
              const lastIndex = nextCandles.length - 1
              if (nextCandles[lastIndex].time === tickId) {
                nextCandles[lastIndex] = nextCandle
              } else {
                nextCandles[lastIndex] = mergeNonMatchingCandle(nextCandles[lastIndex], nextCandle)
              }
            }

            nextMarketBySymbol[quote.tsCode] = {
              quote,
              candles: nextCandles.slice(-MAX_REPLAY_CANDLES),
            }
          }

          return { marketBySymbol: nextMarketBySymbol }
        })
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
        set((state) => ({
          availableCash: state.currentTrainingSession?.startingCash ?? 1000000,
          positions: defaultPositions,
          orders: defaultOrders,
          trainingNotes: [],
          reviewSummary: null,
          wsConnected: false,
          wsReconnectAttempts: 0,
          lastWsSequence: 0,
          currentTick: null,
          marketBySymbol: {},
        }))
      },
    }),
    {
      name: 'trading-storage',
      partialize: (state) => ({
        currentSeasonId: state.currentSeasonId,
        currentAccountId: state.currentAccountId,
        currentTrainingSession: state.currentTrainingSession,
        trainingNotes: state.trainingNotes,
        reviewSummary: state.reviewSummary,
        selectedSymbol: state.selectedSymbol,
      }),
    },
  ),
)
