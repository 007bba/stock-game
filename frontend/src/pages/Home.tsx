import { Button, Card, Col, Row, Space, Tag, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { TRAINING_PRESETS } from '../services/trainingCatalog'
import { useAuthStore } from '../stores/authStore'
import { useTradingStore } from '../stores/tradingStore'

const featureItems = [
  {
    title: '历史行情回放',
    description: '只保留训练真正需要的回放能力，不再把产品做成模拟券商。',
    icon: '01',
  },
  {
    title: '模拟买卖 + 理由',
    description: '每次下单必须写理由，把“冲动”变成可复盘的记录。',
    icon: '02',
  },
  {
    title: '训练后复盘',
    description: '结束后看收益、执行纪律和理由覆盖率，直接指出问题。',
    icon: '03',
  },
]

function HomePage() {
  const navigate = useNavigate()
  const currentUser = useAuthStore((state) => state.currentUser)
  const currentTrainingSession = useTradingStore((state) => state.currentTrainingSession)
  const reviewSummary = useTradingStore((state) => state.reviewSummary)
  const startTrainingSession = useTradingStore((state) => state.startTrainingSession)

  const handleStart = (presetId: string): void => {
    const preset = TRAINING_PRESETS.find((item) => item.id === presetId)
    if (!preset) {
      return
    }

    if (!currentUser) {
      message.info('登录后才能开始训练和保存复盘结果')
      navigate(`/login?nextPreset=${encodeURIComponent(preset.id)}`)
      return
    }

    startTrainingSession({
      presetId: preset.id,
      title: preset.title,
      focus: preset.focus,
      description: preset.description,
      symbolUniverse: preset.symbolUniverse,
      defaultSymbol: preset.defaultSymbol,
      dateRange: preset.dateRange,
      startingCash: preset.startingCash,
      datasetSeasonId: preset.seasonId,
    })
    navigate('/train')
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card style={{ borderRadius: 24 }}>
        <Row gutter={[24, 24]} align="middle">
          <Col xs={24} lg={15}>
            <Space direction="vertical" size="middle">
              <Tag color="gold" style={{ width: 'fit-content' }}>
                Stock Game v2
              </Tag>
              <Typography.Title level={1} style={{ margin: 0 }}>
                闭市也能练交易决策，不再做“模拟券商”。
              </Typography.Title>
              <Typography.Paragraph type="secondary" style={{ fontSize: 16, marginBottom: 0 }}>
                v2 只保留四件事：历史行情回放、模拟下单、记录理由、复盘评分。目标不是把功能堆满，
                而是让你完整跑完一次“看盘、下单、解释、复盘”的训练闭环。
              </Typography.Paragraph>
              <Space wrap>
                <Button type="primary" size="large" onClick={() => handleStart(TRAINING_PRESETS[0].id)}>
                  开始一场训练
                </Button>
                {currentTrainingSession && (
                  <Button size="large" onClick={() => navigate('/train')}>
                    继续当前训练
                  </Button>
                )}
                {reviewSummary && (
                  <Button size="large" onClick={() => navigate('/review')}>
                    查看最近复盘
                  </Button>
                )}
              </Space>
            </Space>
          </Col>
          <Col xs={24} lg={9}>
            <Card
              style={{
                borderRadius: 20,
                background: 'linear-gradient(180deg, rgba(255,255,255,0.96), rgba(244,247,255,0.92))',
              }}
            >
              <Space direction="vertical" size="small" style={{ width: '100%' }}>
                <Typography.Text type="secondary">当前产品边界</Typography.Text>
                <Typography.Title level={4} style={{ margin: 0 }}>
                  选择历史行情 {'->'} 回放 {'->'} 下单 {'->'} 写理由 {'->'} 复盘
                </Typography.Title>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  先把这个闭环做扎实，再考虑别的东西。社区、排行榜和复杂赛制暂时都不进 v2。
                </Typography.Paragraph>
              </Space>
            </Card>
          </Col>
        </Row>
      </Card>

      <Row gutter={[16, 16]}>
        {featureItems.map((item) => (
          <Col xs={24} md={8} key={item.title}>
            <Card style={{ height: '100%', borderRadius: 20 }}>
              <Space direction="vertical" size="small">
                <Typography.Text style={{ fontSize: 22 }}>{item.icon}</Typography.Text>
                <Typography.Title level={4} style={{ margin: 0 }}>
                  {item.title}
                </Typography.Title>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  {item.description}
                </Typography.Paragraph>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      <Card title="训练场次" style={{ borderRadius: 20 }}>
        <Row gutter={[16, 16]}>
          {TRAINING_PRESETS.map((preset) => (
            <Col xs={24} xl={8} key={preset.id}>
              <Card
                style={{ height: '100%', borderRadius: 18 }}
                actions={[
                  <Button type="link" onClick={() => handleStart(preset.id)} key={preset.id}>
                    进入训练
                  </Button>,
                ]}
              >
                <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                  <Space wrap>
                    {preset.tags.map((tag) => (
                      <Tag key={tag}>{tag}</Tag>
                    ))}
                  </Space>
                  <Typography.Title level={4} style={{ margin: 0 }}>
                    {preset.title}
                  </Typography.Title>
                  <Typography.Paragraph type="secondary" style={{ minHeight: 66, marginBottom: 0 }}>
                    {preset.description}
                  </Typography.Paragraph>
                  <Typography.Text strong>{preset.focus}</Typography.Text>
                  <Typography.Text type="secondary">数据片段：{preset.dateRange}</Typography.Text>
                  <Typography.Text type="secondary">
                    股票池：{preset.symbolUniverse.join(' / ')}
                  </Typography.Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>
    </Space>
  )
}

export default HomePage
