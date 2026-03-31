import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Grid,
  List,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  message,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import AccountInfo from '../components/AccountInfo'
import KlineChart from '../components/KlineChart'
import MultiStockGrid, { type GridSize } from '../components/MultiStockGrid'
import OrderBook from '../components/OrderBook'
import OrderForm, { type TradeSide } from '../components/OrderForm'
import OrderList from '../components/OrderList'
import PositionList, { type PositionItem } from '../components/PositionList'
import { DEFAULT_DEMO_SEASON_ID } from '../config/demoSeason'
import { useTradingWebSocket } from '../hooks/useTradingWebSocket'
import {
  SUPPORTED_SYMBOLS,
  getMockLastPrice,
  getMockOrderBook,
  startMockOrderBookFeed,
  submitMockOrder,
  type MockOrderBookSnapshot,
} from '../services/mockTrading'
import {
  advanceTickApi,
  extractApiErrorMessage,
  getCurrentTickSnapshotApi,
  listOrdersApi,
  placeOrderApi,
  shouldFallbackToMock,
  toUiOrder,
} from '../services/tradingApi'
import {
  extractSeasonApiErrorMessage,
  getSeasonAccountApi,
  joinSeasonApi,
  shouldFallbackToMockSeason,
} from '../services/seasonApi'
import { useTradingStore } from '../stores/tradingStore'

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
  const navigate = useNavigate()
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md

  const currentSeasonId = useTradingStore((state) => state.currentSeasonId)
  const currentAccountId = useTradingStore((state) => state.currentAccountId)
  const currentTrainingSession = useTradingStore((state) => state.currentTrainingSession)
  const trainingNotes = useTradingStore((state) => state.trainingNotes)
  const selectedSymbol = useTradingStore((state) => state.selectedSymbol)
  const availableCash = useTradingStore((state) => state.availableCash)
  const positions = useTradingStore((state) => state.positions)
  const orders = useTradingStore((state) => state.orders)
  const wsConnected = useTradingStore((state) => state.wsConnected)
  const wsReconnectAttempts = useTradingStore((state) => state.wsReconnectAttempts)
  const currentTick = useTradingStore((state) => state.currentTick)
  const marketBySymbol = useTradingStore((state) => state.marketBySymbol)
  const setSelectedSymbol = useTradingStore((state) => state.setSelectedSymbol)
  const setCurrentAccount = useTradingStore((state) => state.setCurrentAccount)
  const setAvailableCash = useTradingStore((state) => state.setAvailableCash)
  const setPositions = useTradingStore((state) => state.setPositions)
  const setOrders = useTradingStore((state) => state.setOrders)
  const setCurrentTick = useTradingStore((state) => state.setCurrentTick)
  const applyTickQuotes = useTradingStore((state) => state.applyTickQuotes)
  const prependOrder = useTradingStore((state) => state.prependOrder)
  const recordTradeNote = useTradingStore((state) => state.recordTradeNote)
  const finishTrainingSession = useTradingStore((state) => state.finishTrainingSession)

  const seasonId = currentSeasonId ?? currentTrainingSession?.datasetSeasonId ?? DEFAULT_DEMO_SEASON_ID
  const canUseReplay = !FORCE_MOCK_TRADING && currentSeasonId !== null
  const canUseTradingApi = canUseReplay && currentAccountId !== null

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false)
  const [gridSize, setGridSize] = useState<GridSize>(5)
  const [currentBook, setCurrentBook] = useState<MockOrderBookSnapshot>(() => getMockOrderBook(selectedSymbol))
  const [autoPlaySpeed, setAutoPlaySpeed] = useState<number>(0)

  useTradingWebSocket({ enabled: canUseReplay })

  useEffect(() => {
    setCurrentBook(getMockOrderBook(selectedSymbol))
    const stopFeed = startMockOrderBookFeed(selectedSymbol, setCurrentBook)
    return stopFeed
  }, [selectedSymbol])

  useEffect(() => {
    if (FORCE_MOCK_TRADING || currentSeasonId === null || currentTrainingSession === null) {
      return
    }

    let disposed = false
    void joinSeasonApi(currentSeasonId)
      .then(async (joined) => {
        if (disposed) {
          return
        }

        setCurrentAccount(joined.accountId)
        const snapshot = await getSeasonAccountApi(currentSeasonId)
        if (disposed) {
          return
        }

        setAvailableCash(snapshot.availableCash)
        setPositions(snapshot.positions)
      })
      .catch((error) => {
        if (disposed || shouldFallbackToMockSeason(error)) {
          return
        }
        message.warning(extractSeasonApiErrorMessage(error, '加入训练赛季失败'))
      })

    return () => {
      disposed = true
    }
  }, [
    currentSeasonId,
    currentTrainingSession,
    setAvailableCash,
    setCurrentAccount,
    setPositions,
  ])

  useEffect(() => {
    if (!canUseTradingApi || currentSeasonId === null) {
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
        // Keep local state when the list API is unavailable.
      })

    return () => {
      disposed = true
    }
  }, [canUseTradingApi, currentSeasonId, selectedSymbol, setOrders])

  useEffect(() => {
    if (!canUseReplay || currentSeasonId === null) {
      return
    }

    let disposed = false
    void getCurrentTickSnapshotApi(currentSeasonId)
      .then((snapshot) => {
        if (disposed) {
          return
        }

        setCurrentTick({
          tickId: snapshot.tickId,
          seasonId: snapshot.seasonId,
          gameDayNo: snapshot.gameDayNo,
          minuteOfDay: snapshot.minuteOfDay,
          phase: snapshot.phase,
          matchingMode: snapshot.matchingMode,
          isTradable: snapshot.isTradable,
          isMatchingPoint: snapshot.isMatchingPoint,
          nextTickId: snapshot.nextTickId ?? null,
          nextTickAt: snapshot.nextTickAt ?? null,
        })
        applyTickQuotes(snapshot.tickId, snapshot.quotes, snapshot.isMatchingPoint)
      })
      .catch(() => {
        // Keep mock state only when replay snapshot is unavailable.
      })

    return () => {
      disposed = true
    }
  }, [applyTickQuotes, canUseReplay, currentSeasonId, setCurrentTick])

  useEffect(() => {
    if (autoPlaySpeed === 0 || !canUseReplay || currentSeasonId === null) {
      return
    }

    const timer = setInterval(() => {
      void advanceTickApi(currentSeasonId).catch(() => {
        // Ignore errors during auto-play.
      })
    }, autoPlaySpeed)

    return () => {
      clearInterval(timer)
    }
  }, [autoPlaySpeed, canUseReplay, currentSeasonId])

  const symbolOptions = useMemo(() => {
    return currentTrainingSession?.symbolUniverse ?? SUPPORTED_SYMBOLS
  }, [currentTrainingSession])

  const positionsWithLastPrice = useMemo(() => {
    return positions.map((item) => ({
      ...item,
      lastPrice: marketBySymbol[item.tsCode]?.quote.refPrice ?? getMockLastPrice(item.tsCode),
    }))
  }, [marketBySymbol, positions])

  const selectedSymbolCandles = useMemo(() => {
    return marketBySymbol[selectedSymbol]?.candles ?? []
  }, [marketBySymbol, selectedSymbol])

  const selectedAuctionHint = useMemo(() => {
    return marketBySymbol[selectedSymbol]?.quote.auctionHintLevel ?? 0
  }, [marketBySymbol, selectedSymbol])

  const selectedAuctionImbalance = useMemo(() => {
    return marketBySymbol[selectedSymbol]?.quote.auctionImbalanceRatio ?? null
  }, [marketBySymbol, selectedSymbol])

  const selectedSymbolQuote = useMemo(() => {
    return marketBySymbol[selectedSymbol]?.quote
  }, [marketBySymbol, selectedSymbol])

  const gridItems = useMemo(() => {
    const entries = Object.values(marketBySymbol)
      .sort((left, right) => right.quote.pctChange - left.quote.pctChange)
      .map((item) => ({
        tsCode: item.quote.tsCode,
        refPrice: item.quote.refPrice,
        pctChange: item.quote.pctChange,
        isLimitUp: item.quote.isLimitUp,
        isLimitDown: item.quote.isLimitDown,
        isSelected: item.quote.tsCode === selectedSymbol,
        candles: item.candles,
      }))

    if (entries.length > 0) {
      return entries
    }

    return symbolOptions.map((tsCode) => ({
      tsCode,
      refPrice: getMockLastPrice(tsCode),
      pctChange: 0,
      isLimitUp: false,
      isLimitDown: false,
      isSelected: tsCode === selectedSymbol,
      candles: [],
    }))
  }, [marketBySymbol, selectedSymbol, symbolOptions])

  const totalAsset = useMemo(() => {
    const holdingValue = positionsWithLastPrice.reduce(
      (sum, item) => sum + item.qty * (item.lastPrice ?? item.avgPrice),
      0,
    )
    return availableCash + holdingValue
  }, [availableCash, positionsWithLastPrice])

  const sessionReturnPct = useMemo(() => {
    const base = currentTrainingSession?.startingCash ?? 1000000
    return base > 0 ? ((totalAsset - base) / base) * 100 : 0
  }, [currentTrainingSession, totalAsset])

  const recentNotes = useMemo(() => trainingNotes.slice(0, 5), [trainingNotes])

  const handleSubmit = async (params: {
    side: TradeSide
    price: number
    qty: number
    reason: string
  }): Promise<void> => {
    setIsSubmitting(true)
    try {
      if (canUseTradingApi && currentSeasonId !== null && currentAccountId !== null) {
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
          prependOrder(uiOrder)
          recordTradeNote({
            orderId: uiOrder.orderId,
            symbol: selectedSymbol,
            side: params.side,
            price: params.price,
            qty: params.qty,
            content: params.reason.trim(),
            tickId: currentTick?.tickId ?? null,
            orderStatus: uiOrder.status,
          })

          const executedQty = Math.max(0, apiOrder.quantity - apiOrder.remainingQty)
          const cashDelta = params.side === 'BUY' ? -executedQty * params.price : executedQty * params.price

          if (cashDelta !== 0) {
            setAvailableCash(round2(useTradingStore.getState().availableCash + cashDelta))
          }
          if (executedQty > 0) {
            setPositions(
              applyExecutionToPositions(useTradingStore.getState().positions, {
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
            message.info('已记录理由，委托已提交，等待撮合')
          } else if (uiOrder.status === 'PARTIAL') {
            message.warning(`已记录理由，后端部分成交：${executedQty}/${params.qty}`)
          } else {
            message.success(`已记录理由，后端成交：${params.side} ${selectedSymbol} x ${executedQty}`)
          }
          return
        } catch (error) {
          if (!shouldFallbackToMock(error)) {
            message.error(extractApiErrorMessage(error, '后端下单失败'))
            return
          }
          message.warning('行情回放仍可用，但交易接口不可用，已切回本地模拟下单')
        }
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

      prependOrder(result.order)
      recordTradeNote({
        orderId: result.order.orderId,
        symbol: selectedSymbol,
        side: params.side,
        price: params.price,
        qty: params.qty,
        content: params.reason.trim(),
        tickId: currentTick?.tickId ?? null,
        orderStatus: result.order.status,
      })

      if (result.cashDelta !== 0) {
        setAvailableCash(round2(useTradingStore.getState().availableCash + result.cashDelta))
      }

      if (result.executedQty > 0) {
        setPositions(
          applyExecutionToPositions(useTradingStore.getState().positions, {
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
        message.info(`已记录理由，等待成交：${params.side} ${selectedSymbol}`)
      } else if (result.order.status === 'PARTIAL') {
        message.warning(`已记录理由，部分成交：${result.executedQty}/${params.qty}`)
      } else {
        message.success(`已记录理由，成交成功：${params.side} ${selectedSymbol} x ${result.executedQty}`)
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleFinish = (): void => {
    const summary = finishTrainingSession()
    if (!summary) {
      message.warning('当前没有可结束的训练场次')
      return
    }
    message.success('训练已结束，正在打开复盘页')
    navigate('/review')
  }

  if (!currentTrainingSession) {
    return (
      <Card style={{ borderRadius: 20 }}>
        <Alert
          type="info"
          showIcon
          message="还没有开始训练"
          description="先从首页选择一个历史片段，训练页才会绑定回放场景和复盘目标。"
          action={
            <Button type="primary" onClick={() => navigate('/')}>
              去首页选场次
            </Button>
          }
        />
      </Card>
    )
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Typography.Title level={2} style={{ margin: 0 }}>
          {currentTrainingSession.title}
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          {currentTrainingSession.focus}
        </Typography.Paragraph>
      </Space>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={16}>
          <Card style={{ borderRadius: 20 }}>
            <Row justify="space-between" align={isMobile ? 'top' : 'middle'} gutter={[12, 12]}>
              <Col xs={24} lg={16}>
                <Space wrap>
                  <Tag color="blue">{currentTrainingSession.dateRange}</Tag>
                  <Tag color={canUseReplay ? 'green' : 'orange'}>
                    {canUseReplay ? '历史行情回放已接入' : '本地演示模式'}
                  </Tag>
                  <Tag color={canUseTradingApi ? 'cyan' : 'default'}>
                    {canUseTradingApi ? '交易接口可用' : '交易走本地模拟'}
                  </Tag>
                  <Tag color={wsConnected ? 'success' : wsReconnectAttempts > 0 ? 'warning' : 'default'}>
                    {wsConnected ? '实时连接正常' : wsReconnectAttempts > 0 ? `重连中 ${wsReconnectAttempts}/5` : '未连接'}
                  </Tag>
                  {currentTick && (
                    <Tag color={currentTick.isMatchingPoint ? 'red' : 'geekblue'}>
                      T{currentTick.gameDayNo} M{currentTick.minuteOfDay} {currentTick.phase}
                    </Tag>
                  )}
                  {currentTick &&
                    (currentTick.phase === 'open_auction' || currentTick.phase === 'close_auction') &&
                    selectedAuctionHint > 0 && (
                      <Tag color={selectedAuctionHint >= 2 ? 'orange' : 'gold'}>
                        竞价提示 L{selectedAuctionHint}
                        {selectedAuctionImbalance !== null ? ` · 失衡${(selectedAuctionImbalance * 100).toFixed(1)}%` : ''}
                      </Tag>
                    )}
                </Space>
              </Col>
              <Col xs={24} lg={8}>
                <Space style={{ width: isMobile ? '100%' : undefined }}>
                  <Typography.Text type="secondary">观察标的</Typography.Text>
                  <Select
                    style={{ width: isMobile ? '100%' : 180 }}
                    value={selectedSymbol}
                    onChange={setSelectedSymbol}
                    options={symbolOptions.map((code) => ({ label: code, value: code }))}
                  />
                </Space>
              </Col>
            </Row>
          </Card>
        </Col>

        <Col xs={24} xl={8}>
          <Card style={{ borderRadius: 20 }}>
            <Row gutter={[12, 12]}>
              <Col span={12}>
                <Statistic title="总资产" value={totalAsset} precision={2} />
              </Col>
              <Col span={12}>
                <Statistic title="收益率" value={sessionReturnPct} precision={2} suffix="%" />
              </Col>
              <Col span={12}>
                <Statistic title="操作次数" value={orders.length} />
              </Col>
              <Col span={12}>
                <Statistic title="已写理由" value={trainingNotes.length} />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {!canUseReplay && (
        <Alert
          type="warning"
          showIcon
          message="当前没有绑定历史行情数据"
          description={`会继续使用本地价格和盘口演示。若要接通后端回放，请确认当前训练绑定的数据集 seasonId（默认 ${seasonId}）可用。`}
        />
      )}

      {canUseReplay && !canUseTradingApi && (
        <Alert
          type="info"
          showIcon
          message="当前模式：回放走后端，交易走本地模拟"
          description="这符合 v2 先做训练闭环的目标。你可以先把看盘、下单理由和复盘流程跑通，再补后端训练场次模型。"
        />
      )}

      <Card style={{ borderRadius: 20 }}>
        <Space wrap>
          <Typography.Text type="secondary">回放控制</Typography.Text>
          <Button size="small" type={autoPlaySpeed === 0 ? 'primary' : 'default'} onClick={() => setAutoPlaySpeed(0)}>
            暂停
          </Button>
          <Button
            size="small"
            type={autoPlaySpeed === 2000 ? 'primary' : 'default'}
            onClick={() => setAutoPlaySpeed(2000)}
            disabled={!canUseReplay}
          >
            2秒
          </Button>
          <Button
            size="small"
            type={autoPlaySpeed === 1000 ? 'primary' : 'default'}
            onClick={() => setAutoPlaySpeed(1000)}
            disabled={!canUseReplay}
          >
            1秒
          </Button>
          <Button
            size="small"
            type={autoPlaySpeed === 500 ? 'primary' : 'default'}
            onClick={() => setAutoPlaySpeed(500)}
            disabled={!canUseReplay}
          >
            0.5秒
          </Button>
          <Button
            size="small"
            type={autoPlaySpeed === 200 ? 'primary' : 'default'}
            onClick={() => setAutoPlaySpeed(200)}
            disabled={!canUseReplay}
          >
            0.2秒
          </Button>
          <Button type="primary" ghost onClick={handleFinish}>
            结束训练并复盘
          </Button>
        </Space>
      </Card>

      <MultiStockGrid
        gridSize={gridSize}
        onGridSizeChange={setGridSize}
        items={gridItems}
        onSelect={setSelectedSymbol}
      />

      <Row gutter={[16, 16]}>
        <Col xs={{ span: 24, order: 2 }} lg={{ span: 8, order: 1 }} xl={{ span: 6, order: 1 }}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <OrderForm submitting={isSubmitting} onSubmit={(params) => void handleSubmit(params)} />
            <OrderBook bids={currentBook.bids} asks={currentBook.asks} />
            <Card title="最近记录的理由" style={{ borderRadius: 20 }}>
              <List
                locale={{ emptyText: '还没有记录理由' }}
                dataSource={recentNotes}
                renderItem={(item) => (
                  <List.Item>
                    <Space direction="vertical" size={2} style={{ width: '100%' }}>
                      <Space wrap>
                        <Tag color={item.side === 'BUY' ? 'red' : 'green'}>{item.side}</Tag>
                        <Typography.Text strong>{item.symbol}</Typography.Text>
                        <Typography.Text type="secondary">
                          {item.price.toFixed(2)} x {item.qty}
                        </Typography.Text>
                      </Space>
                      <Typography.Text>{item.content}</Typography.Text>
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
          </Space>
        </Col>

        <Col xs={{ span: 24, order: 1 }} lg={{ span: 16, order: 2 }} xl={{ span: 12, order: 2 }}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <KlineChart
              symbol={selectedSymbol}
              height={isMobile ? 320 : 420}
              candles={selectedSymbolCandles}
              isLimitUp={selectedSymbolQuote?.isLimitUp}
              isLimitDown={selectedSymbolQuote?.isLimitDown}
            />
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
