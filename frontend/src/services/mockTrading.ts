import type { OrderBookLevel } from '../components/OrderBook'
import type { TradeSide } from '../components/OrderForm'
import type { OrderItem } from '../components/OrderList'
import type { PositionItem } from '../components/PositionList'

export interface MockOrderBookSnapshot {
  bids: OrderBookLevel[]
  asks: OrderBookLevel[]
}

export interface SubmitMockOrderParams {
  symbol: string
  side: TradeSide
  price: number
  qty: number
}

export interface SubmitMockOrderContext {
  availableCash: number
  positions: PositionItem[]
}

export interface SubmitMockOrderResult {
  order: OrderItem
  executedQty: number
  cashDelta: number
  rejectReason?: string
}

export const SUPPORTED_SYMBOLS: string[] = ['600000.SH', '000001.SZ', '600519.SH']

const baseLastPrice: Record<string, number> = {
  '600000.SH': 10.34,
  '000001.SZ': 12.22,
  '600519.SH': 1720.5,
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function orderId(): string {
  return `MOCK-${Date.now()}-${Math.floor(Math.random() * 900 + 100)}`
}

function symbolSeed(symbol: string): number {
  return symbol.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0)
}

function holdQty(positions: PositionItem[], symbol: string): number {
  return positions.find((item) => item.tsCode === symbol)?.qty ?? 0
}

function buildSnapshot(symbol: string, tick: number): MockOrderBookSnapshot {
  const seed = symbolSeed(symbol)
  const base = getMockLastPrice(symbol)
  const wobble = Math.sin((seed + tick) / 7) * (base * 0.002)
  const mid = round2(base + wobble)

  const bids: OrderBookLevel[] = Array.from({ length: 5 }, (_, index) => ({
    price: round2(mid - 0.01 * (index + 1)),
    qty: 600 + ((seed + tick * 37 + index * 71) % 38) * 100,
  }))

  const asks: OrderBookLevel[] = Array.from({ length: 5 }, (_, index) => ({
    price: round2(mid + 0.01 * (index + 1)),
    qty: 700 + ((seed + tick * 29 + index * 83) % 36) * 100,
  }))

  return { bids, asks }
}

function resolveFill(seed: number): { status: OrderItem['status']; ratio: number } {
  const mod = seed % 10
  if (mod < 2) {
    return { status: 'PENDING', ratio: 0 }
  }
  if (mod < 5) {
    return { status: 'PARTIAL', ratio: 0.5 }
  }
  return { status: 'FILLED', ratio: 1 }
}

export function getMockLastPrice(symbol: string): number {
  return baseLastPrice[symbol] ?? 10
}

export function getMockOrderBook(symbol: string): MockOrderBookSnapshot {
  return buildSnapshot(symbol, 0)
}

export function startMockOrderBookFeed(
  symbol: string,
  onUpdate: (snapshot: MockOrderBookSnapshot) => void,
  intervalMs = 1200,
): () => void {
  let tick = 0

  const emit = () => {
    tick += 1
    onUpdate(buildSnapshot(symbol, tick))
  }

  emit()
  const timer = window.setInterval(emit, intervalMs)

  return () => {
    window.clearInterval(timer)
  }
}

export async function submitMockOrder(
  params: SubmitMockOrderParams,
  context: SubmitMockOrderContext,
): Promise<SubmitMockOrderResult> {
  await new Promise<void>((resolve) => {
    setTimeout(resolve, 240)
  })

  if (params.qty <= 0 || params.qty % 100 !== 0) {
    const order: OrderItem = {
      orderId: orderId(),
      tsCode: params.symbol,
      side: params.side,
      qty: params.qty,
      price: round2(params.price),
      status: 'REJECTED',
    }
    return {
      order,
      executedQty: 0,
      cashDelta: 0,
      rejectReason: '数量必须是 100 的正整数倍',
    }
  }

  if (params.price <= 0) {
    const order: OrderItem = {
      orderId: orderId(),
      tsCode: params.symbol,
      side: params.side,
      qty: params.qty,
      price: round2(params.price),
      status: 'REJECTED',
    }
    return {
      order,
      executedQty: 0,
      cashDelta: 0,
      rejectReason: '价格必须大于 0',
    }
  }

  const notional = params.price * params.qty
  if (params.side === 'BUY' && notional > context.availableCash) {
    const order: OrderItem = {
      orderId: orderId(),
      tsCode: params.symbol,
      side: params.side,
      qty: params.qty,
      price: round2(params.price),
      status: 'REJECTED',
    }
    return {
      order,
      executedQty: 0,
      cashDelta: 0,
      rejectReason: '可用资金不足',
    }
  }

  const canSellQty = holdQty(context.positions, params.symbol)
  if (params.side === 'SELL' && params.qty > canSellQty) {
    const order: OrderItem = {
      orderId: orderId(),
      tsCode: params.symbol,
      side: params.side,
      qty: params.qty,
      price: round2(params.price),
      status: 'REJECTED',
    }
    return {
      order,
      executedQty: 0,
      cashDelta: 0,
      rejectReason: '可卖数量不足',
    }
  }

  const seed = Math.floor(Date.now() / 1000) + params.qty + symbolSeed(params.symbol)
  const fill = resolveFill(seed)
  const executedQty = Math.floor((params.qty * fill.ratio) / 100) * 100
  const executedNotional = round2(executedQty * params.price)
  const cashDelta = params.side === 'BUY' ? -executedNotional : executedNotional

  return {
    order: {
      orderId: orderId(),
      tsCode: params.symbol,
      side: params.side,
      qty: params.qty,
      price: round2(params.price),
      status: fill.status,
    },
    executedQty,
    cashDelta,
  }
}
