import { Alert, Button, Card, Col, Progress, Row, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { OrderItem } from '../components/OrderList'
import { useTradingStore } from '../stores/tradingStore'

interface ReviewOrderRow extends OrderItem {
  note?: string
}

const statusColor: Record<OrderItem['status'], string> = {
  PENDING: 'processing',
  PARTIAL: 'warning',
  FILLED: 'success',
  CANCELED: 'default',
  REJECTED: 'error',
  EXPIRED: 'default',
}

function ReviewPage() {
  const navigate = useNavigate()
  const reviewSummary = useTradingStore((state) => state.reviewSummary)
  const clearReviewSummary = useTradingStore((state) => state.clearReviewSummary)

  const rows = useMemo<ReviewOrderRow[]>(() => {
    if (!reviewSummary) {
      return []
    }

    return reviewSummary.orders.map((order) => ({
      ...order,
      note: reviewSummary.notes.find((item) => item.orderId === order.orderId)?.content,
    }))
  }, [reviewSummary])

  const columns = useMemo<ColumnsType<ReviewOrderRow>>(
    () => [
      { title: '股票', dataIndex: 'tsCode', key: 'tsCode', width: 120 },
      { title: '方向', dataIndex: 'side', key: 'side', width: 90 },
      { title: '数量', dataIndex: 'qty', key: 'qty', width: 90 },
      { title: '价格', dataIndex: 'price', key: 'price', width: 90 },
      {
        title: '状态',
        dataIndex: 'status',
        key: 'status',
        width: 100,
        render: (value: ReviewOrderRow['status']) => <Tag color={statusColor[value]}>{value}</Tag>,
      },
      {
        title: '操作理由',
        dataIndex: 'note',
        key: 'note',
        render: (value: string | undefined) => value ?? <Typography.Text type="secondary">未记录</Typography.Text>,
      },
    ],
    [],
  )

  if (!reviewSummary) {
    return (
      <Card style={{ borderRadius: 20 }}>
        <Alert
          type="info"
          showIcon
          message="还没有可展示的复盘结果"
          description="先完成一场训练并点击“结束训练”，这里才会生成收益和执行纪律摘要。"
          action={
            <Button type="primary" onClick={() => navigate('/train')}>
              去训练页
            </Button>
          }
        />
      </Card>
    )
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card style={{ borderRadius: 20 }}>
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <Typography.Title level={2} style={{ margin: 0 }}>
            {reviewSummary.title}
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            {reviewSummary.focus}
          </Typography.Paragraph>
          <Space wrap>
            <Tag color="blue">开始：{new Date(reviewSummary.startedAt).toLocaleString()}</Tag>
            <Tag color="purple">结束：{new Date(reviewSummary.completedAt).toLocaleString()}</Tag>
            <Tag color={reviewSummary.netPnl >= 0 ? 'success' : 'error'}>
              收益 {reviewSummary.netPnl >= 0 ? '+' : ''}
              {reviewSummary.netPnl.toFixed(2)}
            </Tag>
          </Space>
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12} xl={6}>
          <Card style={{ borderRadius: 18 }}>
            <Typography.Text type="secondary">总资产</Typography.Text>
            <Typography.Title level={3} style={{ margin: '8px 0 0' }}>
              ¥{reviewSummary.totalAsset.toLocaleString()}
            </Typography.Title>
          </Card>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <Card style={{ borderRadius: 18 }}>
            <Typography.Text type="secondary">收益率</Typography.Text>
            <Typography.Title level={3} style={{ margin: '8px 0 0' }}>
              {reviewSummary.returnPct >= 0 ? '+' : ''}
              {reviewSummary.returnPct.toFixed(2)}%
            </Typography.Title>
          </Card>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <Card style={{ borderRadius: 18 }}>
            <Typography.Text type="secondary">执行胜率</Typography.Text>
            <Typography.Title level={3} style={{ margin: '8px 0 0' }}>
              {reviewSummary.winRate.toFixed(1)}%
            </Typography.Title>
          </Card>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <Card style={{ borderRadius: 18 }}>
            <Typography.Text type="secondary">纪律评分</Typography.Text>
            <Typography.Title level={3} style={{ margin: '8px 0 0' }}>
              {reviewSummary.disciplineScore}
            </Typography.Title>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={8}>
          <Card title="训练摘要" style={{ height: '100%', borderRadius: 20 }}>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <div>
                <Typography.Text type="secondary">理由覆盖率</Typography.Text>
                <Progress percent={reviewSummary.noteCoverage} strokeColor="#1677ff" />
              </div>
              <div>
                <Typography.Text type="secondary">纪律评分</Typography.Text>
                <Progress percent={reviewSummary.disciplineScore} strokeColor="#1f8f55" />
              </div>
              <Typography.Text>总操作：{reviewSummary.totalOrders}</Typography.Text>
              <Typography.Text>有效成交：{reviewSummary.executedOrders}</Typography.Text>
              <Typography.Text>拒单次数：{reviewSummary.rejectedOrders}</Typography.Text>
              <Typography.Text>持仓市值：¥{reviewSummary.holdingValue.toLocaleString()}</Typography.Text>
              <Typography.Text>剩余现金：¥{reviewSummary.availableCash.toLocaleString()}</Typography.Text>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={16}>
          <Card title="操作与理由" style={{ borderRadius: 20 }}>
            <Table<ReviewOrderRow>
              rowKey="orderId"
              size="small"
              pagination={false}
              columns={columns}
              dataSource={rows}
              scroll={{ x: 780 }}
            />
          </Card>
        </Col>
      </Row>

      <Card title="复盘提醒" style={{ borderRadius: 20 }}>
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <Typography.Text>
            如果纪律评分低，先看是不是交易过多、拒单过多，或者下单时根本没写清理由。
          </Typography.Text>
          <Typography.Text>
            如果收益不好但理由覆盖率高，通常说明问题不在“乱点”，而在计划本身质量不够。
          </Typography.Text>
          <Space wrap>
            <Button type="primary" onClick={() => navigate('/train')}>
              再练一场
            </Button>
            <Button
              onClick={() => {
                clearReviewSummary()
                navigate('/')
              }}
            >
              返回首页
            </Button>
          </Space>
        </Space>
      </Card>
    </Space>
  )
}

export default ReviewPage
