import { useEffect, useMemo, useRef } from 'react'
import { Card } from 'antd'
import { CandlestickSeries, ColorType, createChart } from 'lightweight-charts'
import type { CandlestickData, Time, UTCTimestamp } from 'lightweight-charts'

interface KlineChartProps {
  symbol?: string
  height?: number
  candles?: Array<{
    time: number
    open: number
    high: number
    low: number
    close: number
  }>
  isLimitUp?: boolean
  isLimitDown?: boolean
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function symbolSeed(symbol: string): number {
  return symbol.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0)
}

function createMockCandles(symbol: string, points = 23): CandlestickData<Time>[] {
  const seed = symbolSeed(symbol)
  const result: CandlestickData<Time>[] = []

  let price = 20 + (seed % 500) / 10
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - points)

  for (let i = 0; i < points; i += 1) {
    const date = new Date(start)
    date.setDate(start.getDate() + i)

    const trend = Math.sin((seed + i) / 10) * 0.7
    const volatility = Math.cos((seed + i) / 4) * 0.45

    const open = Math.max(1, price + trend)
    const close = Math.max(1, open + volatility)
    const high = Math.max(open, close) + 0.35 + Math.abs(Math.sin((seed + i) / 3)) * 0.55
    const low = Math.min(open, close) - 0.35 - Math.abs(Math.cos((seed + i) / 3)) * 0.55

    price = close
    result.push({
      time: Math.floor(date.getTime() / 1000) as UTCTimestamp,
      open: round2(open),
      high: round2(high),
      low: round2(low),
      close: round2(close),
    })
  }

  return result
}

function KlineChart({ symbol = '000001.SZ', height = 320, candles: replayCandles, isLimitUp, isLimitDown }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const candles = useMemo(() => {
    if (replayCandles && replayCandles.length > 0) {
      return replayCandles.map((item) => ({
        time: item.time as UTCTimestamp,
        open: item.open,
        high: item.high,
        low: item.low,
        close: item.close,
      }))
    }
    return createMockCandles(symbol)
  }, [replayCandles, symbol])

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      return
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height: Math.max(220, height - 88),
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#334155',
      },
      grid: {
        vertLines: { color: '#eef2f7' },
        horzLines: { color: '#eef2f7' },
      },
      crosshair: {
        vertLine: { color: '#94a3b8' },
        horzLine: { color: '#94a3b8' },
      },
      rightPriceScale: {
        borderColor: '#e2e8f0',
      },
      timeScale: {
        borderColor: '#e2e8f0',
      },
    })

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#ef5350',
      downColor: '#26a69a',
      wickUpColor: '#ef5350',
      wickDownColor: '#26a69a',
      borderVisible: false,
    })

    candlestickSeries.setData(candles)
    chart.timeScale().fitContent()

    const handleResize = () => {
      chart.applyOptions({ width: container.clientWidth })
    }

    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [candles, height])

  const statusBadge = isLimitUp ? ' [涨停]' : isLimitDown ? ' [跌停]' : ''

  return (
    <Card 
      title={`K 线图 - ${symbol}${statusBadge}`} 
      style={{ minHeight: height }}
      extra={
        isLimitUp ? (
          <span style={{ color: '#ef5350', fontWeight: 'bold' }}>⭐ 涨停</span>
        ) : isLimitDown ? (
          <span style={{ color: '#26a69a', fontWeight: 'bold' }}>跌停</span>
        ) : null
      }
    >
      <div ref={containerRef} style={{ width: '100%', height: Math.max(220, height - 88) }} />
    </Card>
  )
}

export default KlineChart
