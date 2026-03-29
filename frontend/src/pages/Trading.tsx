import { useEffect, useMemo, useState } from 'react'
import { Alert, Col, Grid, Row, Select, Space, Tag, Typography, message } from 'antd'
import AccountInfo from '../components/AccountInfo'
import KlineChart from '../components/KlineChart'
import OrderBook from '../components/OrderBook'
import OrderForm, { type TradeSide } from '../components/OrderForm'
import OrderList, { type OrderItem } from '../components/OrderList'
import PositionList, { type PositionItem } from '../components/PositionList'
import {
  SUPPORTED_SYMBOLS,
  getMockLastPrice,
  getMockOrderBook,
  startMockOrderBookFeed,
  submitMockOrder,
  type MockOrderBookSnapshot,
} from '../services/mockTrading'
import {
  extractApiErrorMessage,
  listOrdersApi,
  placeOrderApi,
  shouldFallbackToMock,
  toUiOrder,
} from '../services/tradingApi'
import { useTradingStore } from '../stores/tradingStore'

const initialPositions: PositionItem[] = [
  { tsCode: '600000.SH', qty: 1000, avgPrice: 10.21 },
  { tsCode: '000001.SZ', qty: 500, avgPrice: 12.05 },
  { tsCode: '600519.SH', qty: 100, avgPrice: 1698.0 },
]

const DEFAULT_SEASON_ID = Number(import.meta.env.VITE_DEFAULT_SEASON_ID ?? 1)
const FORCE_MOCK_TRADING = String(import.meta.env.VITE_USE_MOCK_TRADING ?? 'false').toLowerCase() === 'true'

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function applyExecutionToPositions(
  positions: PositionItem[],
  params: { symbol: string; side: TradeSide; price: number; executedQty: number },
): PositionItem[] {
  if (params.executedQty <= 0) {
    return positions
  }

  const index = positions.findIndex((item) => item.tsCode === params.symbol)

  if (params.side === 'BUY') {
    if (index < 0) {
      return [
        ...positions,
        {
          tsCode: params.symbol,
          qty: params.executedQty,
          avgPrice: round2(params.price),
        },
      ]
    }

    const target = positions[index]
    const totalQty = target.qty + params.executedQty
    const nextAvg = round2((target.qty * target.avgPrice + params.executedQty * params.price) / totalQty)

    return positions.map((item, posIndex) => {
      if (posIndex !== index) {
        return item
      }
      return {
        ...item,
        qty: totalQty,
        avgPrice: nextAvg,
      }
    })
  }

  if (index < 0) {
    return positions
  }

  const target = positions[index]
  const remainQty = target.qty - params.executedQty
  if (remainQty <= 0) {
    return positions.filter((item) => item.tsCode !== params.symbol)
  }

  return positions.map((item, posIndex) => {
    if (posIndex !== index) {
      return item
    }
    return {
      ...item,
      qty: remainQty,
    }
  })
}

function TradingPage() {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md

  const currentSeasonId = useTradingStore((state) => state.currentSeasonId)
  const currentAccountId = useTradingStore((state) => state.currentAccountId)
  const selectedSymbol = useTradingStore((state) => state.selectedSymbol)
  const setSelectedSymbol = useTradingStore((state) => state.setSelectedSymbol)
  const seasonId = currentSeasonId ?? DEFAULT_SEASON_ID
  const hasBoundAccount = currentSeasonId !== null && currentAccountId !== null

  const [availableCash, setAvailableCash] = useState<number>(1000000)
  const [positions, setPositions] = useState<PositionItem[]>(initialPositions)
  const [orders, setOrders] = useState<OrderItem[]>([
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
  ])
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false)
  const [currentBook, setCurrentBook] = useState<MockOrderBookSnapshot>(() =>
    getMockOrderBook(selectedSymbol),
  )

  useEffect(() => {
    setCurrentBook(getMockOrderBook(selectedSymbol))
    const stopFeed = startMockOrderBookFeed(selectedSymbol, setCurrentBook)
    return stopFeed
  }, [selectedSymbol])

  useEffect(() => {
    if (FORCE_MOCK_TRADING || currentSeasonId === null || currentAccountId === null) {
      return
    }

    let disposed = false
    void listOrdersApi({ seasonId: currentSeasonId, tsCode: selectedSymbol })
      .then((apiOrders) => {
        if (disposed || apiOrders.length === 0) {
          return
        }
        setOrders(apiOrders.map((item) => toUiOrder(item)).reverse().slice(0, 30))
      })
      .catch(() => {
        // Keep existing UI state when backend list API is unavailable.
      })

    return () => {
      disposed = true
    }
  }, [currentAccountId, currentSeasonId, selectedSymbol])

  const positionsWithLastPrice = useMemo(() => {
    return positions.map((item) => ({
      ...item,
      lastPrice: getMockLastPrice(item.tsCode),
    }))
  }, [positions])

  const totalAsset = useMemo(() => {
    const holdingValue = positionsWithLastPrice.reduce(
      (sum, item) => sum + item.qty * (item.lastPrice ?? item.avgPrice),
      0,
    )
    return availableCash + holdingValue
  }, [availableCash, positionsWithLastPrice])

  const handleSubmit = async (params: { side: TradeSide; price: number; qty: number }): Promise<void> => {
    setIsSubmitting(true)
    try {
      if (!FORCE_MOCK_TRADING && currentSeasonId !== null && currentAccountId !== null) {
        try {
          const apiOrder = await placeOrderApi({
            seasonId: currentSeasonId,
            accountId: currentAccountId,
            symbol: selectedSymbol,
            side: params.side,
            price: params.price,
            qty: params.qty,
          })

          const uiOrder = toUiOrder(apiOrder)
          setOrders((prev) => [uiOrder, ...prev].slice(0, 30))

          const executedQty = Math.max(0, apiOrder.quantity - apiOrder.remainingQty)
          const cashDelta = params.side === 'BUY' ? -executedQty * params.price : executedQty * params.price

          if (cashDelta !== 0) {
            setAvailableCash((prev) => round2(prev + cashDelta))
          }
          if (executedQty > 0) {
            setPositions((prev) =>
              applyExecutionToPositions(prev, {
                symbol: selectedSymbol,
                side: params.side,
                price: params.price,
                executedQty,
              }),
            )
          }

          if (uiOrder.status === 'REJECTED') {
            message.error(apiOrder.rejectReason ?? '后端拒单')
          } else if (uiOrder.status === 'PENDING') {
            message.info('后端已接单，等待撮合')
          } else if (uiOrder.status === 'PARTIAL') {
            message.warning(`后端部分成交：${executedQty}/${params.qty}`)
          } else {
            message.success(`后端成交：${params.side} ${selectedSymbol} x ${executedQty}`)
          }
          return
        } catch (error) {
          if (!shouldFallbackToMock(error)) {
            message.error(extractApiErrorMessage(error, '后端下单失败'))
            return
          }
          message.warning('后端交易 API 暂不可用，已自动切换到 mock 下单')
        }
      } else if (!FORCE_MOCK_TRADING && !hasBoundAccount) {
        message.info('当前未绑定赛季账户，已使用 mock 下单')
      }

      const result = await submitMockOrder(
        {
          symbol: selectedSymbol,
          side: params.side,
          price: params.price,
          qty: params.qty,
        },
        {
          availableCash,
          positions,
        },
      )

      setOrders((prev) => [result.order, ...prev].slice(0, 30))

      if (result.cashDelta !== 0) {
        setAvailableCash((prev) => round2(prev + result.cashDelta))
      }

      if (result.executedQty > 0) {
        setPositions((prev) =>
          applyExecutionToPositions(prev, {
            symbol: selectedSymbol,
            side: params.side,
            price: params.price,
            executedQty: result.executedQty,
          }),
        )
      }

      if (result.order.status === 'REJECTED') {
        message.error(result.rejectReason ?? '下单失败')
      } else if (result.order.status === 'PENDING') {
        message.info(`委托已提交，等待成交：${params.side} ${selectedSymbol}`)
      } else if (result.order.status === 'PARTIAL') {
        message.warning(`部分成交：${result.executedQty}/${params.qty}`)
      } else {
        message.success(`成交成功：${params.side} ${selectedSymbol} x ${result.executedQty}`)
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          交易终端
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          P7-T5 到 P7-T12 已推进：三栏布局、K 线、后端下单优先 + mock 回退、响应式优化。
        </Typography.Paragraph>
      </Space>

      {(currentSeasonId === null || currentAccountId === null) && (
        <Alert
          type="warning"
          showIcon
          message="当前未绑定赛季或账户"
          description="请先从赛季大厅加入赛季以完成开户绑定；当前会自动使用 mock 模式演示交易。"
        />
      )}

      <Row justify="space-between" align={isMobile ? 'top' : 'middle'} gutter={[12, 12]}>
        <Col xs={24} md={12}>
          <Space wrap>
            <Tag color="gold">
              {currentSeasonId !== null ? `赛季 #${currentSeasonId}` : `默认赛季 #${seasonId}`}
            </Tag>
            <Tag color={currentAccountId !== null ? 'cyan' : 'orange'}>
              {currentAccountId !== null ? `账户 #${currentAccountId}` : '未绑定账户'}
            </Tag>
            <Tag color="blue">交易日 T+1 规则</Tag>
            {!FORCE_MOCK_TRADING && <Tag color="green">后端 API 优先</Tag>}
          </Space>
        </Col>
        <Col xs={24} md={12}>
          <Space style={{ width: isMobile ? '100%' : undefined }}>
            <Typography.Text type="secondary">交易标的</Typography.Text>
            <Select
              style={{ width: isMobile ? '100%' : 180 }}
              value={selectedSymbol}
              onChange={setSelectedSymbol}
              options={SUPPORTED_SYMBOLS.map((code) => ({ label: code, value: code }))}
            />
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={{ span: 24, order: 2 }} lg={{ span: 8, order: 1 }} xl={{ span: 6, order: 1 }}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <OrderForm submitting={isSubmitting} onSubmit={(params) => void handleSubmit(params)} />
            <OrderBook bids={currentBook.bids} asks={currentBook.asks} />
          </Space>
        </Col>

        <Col xs={{ span: 24, order: 1 }} lg={{ span: 16, order: 2 }} xl={{ span: 12, order: 2 }}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <KlineChart symbol={selectedSymbol} height={isMobile ? 320 : 420} />
            <OrderList orders={orders} />
          </Space>
        </Col>

        <Col xs={{ span: 24, order: 3 }} lg={{ span: 24, order: 3 }} xl={{ span: 6, order: 3 }}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <AccountInfo availableCash={availableCash} totalAsset={totalAsset} />
            <PositionList positions={positionsWithLastPrice} />
          </Space>
        </Col>
      </Row>
    </Space>
  )
}

export default TradingPage
