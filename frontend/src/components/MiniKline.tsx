import { useEffect, useRef } from 'react'
import { AreaSeries, ColorType, createChart } from 'lightweight-charts'
import type { Time, UTCTimestamp } from 'lightweight-charts'
import type { ReplayCandle } from '../stores/tradingStore'

interface MiniKlineProps {
  candles: ReplayCandle[]
  height?: number
  positive?: boolean
}

function MiniKline({ candles, height = 92, positive = true }: MiniKlineProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      return
    }

    if (candles.length === 0) {
      container.replaceChildren()
      return
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: 'transparent',
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      rightPriceScale: {
        visible: false,
      },
      timeScale: {
        visible: false,
      },
      crosshair: {
        vertLine: { visible: false },
        horzLine: { visible: false },
      },
      handleScroll: false,
      handleScale: false,
    })

    const lineColor = positive ? '#d9363e' : '#1677ff'
    const areaColor = positive ? 'rgba(217, 54, 62, 0.22)' : 'rgba(22, 119, 255, 0.20)'

    const series = chart.addSeries(AreaSeries, {
      lineColor,
      topColor: areaColor,
      bottomColor: 'rgba(0, 0, 0, 0)',
      lineWidth: 2,
    })

    const seriesData = candles.map((item) => ({
      time: item.time as UTCTimestamp,
      value: item.close,
    }))
    series.setData(seriesData as Array<{ time: Time; value: number }>)
    chart.timeScale().fitContent()

    const handleResize = () => {
      chart.applyOptions({ width: container.clientWidth })
    }

    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [candles, height, positive])

  return <div ref={containerRef} style={{ width: '100%', height }} />
}

export default MiniKline
