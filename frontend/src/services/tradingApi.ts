import type { TradeSide } from '../components/OrderForm'
import type { OrderItem, OrderStatus } from '../components/OrderList'
import { ApiError, api } from './api'

export type ApiOrderSide = 'buy' | 'sell'

export type ApiOrderStatus =
  | 'pending'
  | 'active'
  | 'partially_filled'
  | 'filled'
  | 'canceled'
  | 'rejected'
  | 'expired'

export interface PlaceOrderApiParams {
  seasonId: number
  accountId: number
  symbol: string
  side: TradeSide
  price: number
  qty: number
}

export interface ApiOrder {
  id: number
  clientOrderId: string
  tsCode: string
  side: ApiOrderSide
  limitPrice: number
  quantity: number
  remainingQty: number
  status: ApiOrderStatus
  rejectCode?: string | null
  rejectReason?: string | null
  createdAt: string
  updatedAt?: string | null
}

export interface ReplayQuoteSnapshot {
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

export interface CurrentTickSnapshot {
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
  quotes: ReplayQuoteSnapshot[]
}

interface PlaceOrderRequest {
  clientOrderId: string
  accountId: number
  tsCode: string
  side: ApiOrderSide
  limitPrice: number
  quantity: number
}

function toApiSide(side: TradeSide): ApiOrderSide {
  return side === 'BUY' ? 'buy' : 'sell'
}

function toUiStatus(status: ApiOrderStatus): OrderStatus {
  if (status === 'active' || status === 'pending') {
    return 'PENDING'
  }
  if (status === 'partially_filled') {
    return 'PARTIAL'
  }
  if (status === 'filled') {
    return 'FILLED'
  }
  if (status === 'canceled') {
    return 'CANCELED'
  }
  if (status === 'expired') {
    return 'EXPIRED'
  }
  return 'REJECTED'
}

function createClientOrderId(): string {
  return `web-${Date.now()}-${Math.floor(Math.random() * 900 + 100)}`
}

export function toUiOrder(order: ApiOrder): OrderItem {
  return {
    orderId: String(order.id),
    tsCode: order.tsCode,
    side: order.side === 'buy' ? 'BUY' : 'SELL',
    qty: order.quantity,
    price: order.limitPrice,
    status: toUiStatus(order.status),
  }
}

export async function placeOrderApi(params: PlaceOrderApiParams): Promise<ApiOrder> {
  const payload: PlaceOrderRequest = {
    clientOrderId: createClientOrderId(),
    accountId: params.accountId,
    tsCode: params.symbol,
    side: toApiSide(params.side),
    limitPrice: params.price,
    quantity: params.qty,
  }

  return api.post<ApiOrder>(`/v1/seasons/${params.seasonId}/orders`, payload)
}

export async function listOrdersApi(params: {
  seasonId: number
  status?: ApiOrderStatus
  tsCode?: string
}): Promise<ApiOrder[]> {
  const search = new URLSearchParams()
  if (params.status) {
    search.set('status', params.status)
  }
  if (params.tsCode) {
    search.set('tsCode', params.tsCode)
  }

  const query = search.toString()
  const path = query
    ? `/v1/seasons/${params.seasonId}/orders?${query}`
    : `/v1/seasons/${params.seasonId}/orders`
  return api.get<ApiOrder[]>(path)
}

export async function getCurrentTickSnapshotApi(seasonId: number): Promise<CurrentTickSnapshot> {
  return api.get<CurrentTickSnapshot>(`/v1/seasons/${seasonId}/ticks/current`)
}

export async function advanceTickApi(seasonId: number): Promise<void> {
  return api.post(`/v1/seasons/${seasonId}/ticks/advance`)
}

export function extractApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message || fallback
  }
  if (error instanceof Error) {
    return error.message || fallback
  }
  return fallback
}

export function shouldFallbackToMock(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status === 404 || error.status >= 500
  }
  if (error instanceof TypeError) {
    return true
  }
  return false
}
