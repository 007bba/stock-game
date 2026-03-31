import { Card, Segmented, Space, Typography } from 'antd'
import MiniKline from './MiniKline'
import type { ReplayCandle } from '../stores/tradingStore'

export type GridSize = 2 | 3 | 4 | 5

export interface MultiStockGridItem {
  tsCode: string
  refPrice: number
  pctChange: number
  isLimitUp: boolean
  isLimitDown: boolean
  isSelected: boolean
  candles: ReplayCandle[]
}

interface MultiStockGridProps {
  gridSize: GridSize
  onGridSizeChange: (size: GridSize) => void
  items: MultiStockGridItem[]
  onSelect: (tsCode: string) => void
}

function formatSignedPercent(value: number): string {
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(2)}%`
}

function MultiStockGrid({ gridSize, onGridSizeChange, items, onSelect }: MultiStockGridProps) {
  const columns = gridSize
  const maxItems = columns * columns
  
  // 按涨幅排序（龙头股置顶）
  const sortedItems = [...items].sort((a, b) => b.pctChange - a.pctChange)
  const visibleItems = sortedItems.slice(0, maxItems)
  
  // 找出龙头股（涨幅最大）
  const leaderSymbol = sortedItems.length > 0 ? sortedItems[0].tsCode : null

  return (
    <Card
      title="多股票并列走势"
      extra={
        <Segmented
          value={gridSize}
          options={[
            { label: '2x2', value: 2 },
            { label: '3x3', value: 3 },
            { label: '4x4', value: 4 },
            { label: '5x5', value: 5 },
          ]}
          onChange={(value) => onGridSizeChange(value as GridSize)}
        />
      }
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
          gap: 10,
        }}
      >
        {visibleItems.map((item) => {
          const isLeader = item.tsCode === leaderSymbol && item.pctChange > 0
          const borderColor = item.isLimitUp
            ? '#cf1322'
            : item.isLimitDown
              ? '#0958d9'
              : isLeader
                ? '#faad14'
                : item.isSelected
                  ? '#1677ff'
                  : '#d9d9d9'

          const toneColor = item.pctChange >= 0 ? '#d9363e' : '#1677ff'

          return (
            <button
              key={item.tsCode}
              type="button"
              onClick={() => onSelect(item.tsCode)}
              style={{
                border: `2px solid ${borderColor}`,
                background: '#ffffff',
                borderRadius: 10,
                textAlign: 'left',
                padding: 8,
                cursor: 'pointer',
                transition: 'all 120ms ease',
              }}
            >
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Space align="baseline" style={{ justifyContent: 'space-between', width: '100%' }}>
                  <Typography.Text strong>
                    {isLeader && '⭐ '}
                    {item.tsCode}
                  </Typography.Text>
                  <Typography.Text style={{ color: toneColor, fontWeight: 700 }}>
                    {formatSignedPercent(item.pctChange)}
                  </Typography.Text>
                </Space>
                <Typography.Text type="secondary">现价 {item.refPrice.toFixed(3)}</Typography.Text>
                <MiniKline candles={item.candles} positive={item.pctChange >= 0} />
              </Space>
            </button>
          )
        })}
      </div>
    </Card>
  )
}

export default MultiStockGrid
