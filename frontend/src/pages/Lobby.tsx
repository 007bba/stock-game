import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Row,
  Segmented,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
  message,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import { createMockSeason, joinMockSeason, listMockSeasons, type LobbySeason } from '../services/mockSeason'
import {
  extractSeasonApiErrorMessage,
  joinSeasonApi,
  shouldFallbackToMockSeason,
} from '../services/seasonApi'
import { useAuthStore } from '../stores/authStore'
import { useTradingStore } from '../stores/tradingStore'

type SeasonFilter = 'all' | '报名中' | '进行中' | '已结束'

interface CreateSeasonFormValues {
  name: string
  initialCash: number
  stockCount: number
  startDate: string
  endDate: string
}

const statusColor: Record<LobbySeason['status'], string> = {
  报名中: 'blue',
  进行中: 'green',
  已结束: 'default',
}

const filterItems: Array<{ label: string; value: SeasonFilter }> = [
  { label: '全部', value: 'all' },
  { label: '报名中', value: '报名中' },
  { label: '进行中', value: '进行中' },
  { label: '已结束', value: '已结束' },
]

function LobbyPage() {
  const navigate = useNavigate()
  const currentUser = useAuthStore((state) => state.currentUser)
  const setCurrentSeason = useTradingStore((state) => state.setCurrentSeason)
  const setCurrentAccount = useTradingStore((state) => state.setCurrentAccount)
  const [createForm] = Form.useForm<CreateSeasonFormValues>()

  const [seasons, setSeasons] = useState<LobbySeason[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false)
  const [isCreating, setIsCreating] = useState<boolean>(false)
  const [joiningSeasonId, setJoiningSeasonId] = useState<number | null>(null)
  const [filter, setFilter] = useState<SeasonFilter>('all')

  const filteredSeasons = useMemo(() => {
    if (filter === 'all') {
      return seasons
    }
    return seasons.filter((season) => season.status === filter)
  }, [seasons, filter])

  const seasonStats = useMemo(() => {
    return {
      total: seasons.length,
      open: seasons.filter((item) => item.status === '报名中').length,
      running: seasons.filter((item) => item.status === '进行中').length,
      joined: seasons.filter((item) => item.joined).length,
    }
  }, [seasons])

  const loadSeasons = useCallback(async (): Promise<void> => {
    setIsLoading(true)
    setErrorMessage(null)

    try {
      const data = await listMockSeasons(currentUser?.id)
      setSeasons(data)
    } catch (error) {
      const text = error instanceof Error ? error.message : '加载赛季失败'
      setErrorMessage(text)
    } finally {
      setIsLoading(false)
    }
  }, [currentUser?.id])

  useEffect(() => {
    void loadSeasons()
  }, [loadSeasons])

  const ensureLogin = (): boolean => {
    if (currentUser) {
      return true
    }
    message.warning('请先登录后再加入或创建赛季')
    navigate('/login')
    return false
  }

  const handleJoin = async (season: LobbySeason): Promise<void> => {
    if (!ensureLogin() || !currentUser) {
      return
    }

    setJoiningSeasonId(season.id)
    try {
      const result = await joinSeasonApi(season.id)
      setSeasons((prev) =>
        prev.map((item) => {
          if (item.id !== season.id) {
            return item
          }
          return {
            ...item,
            joined: true,
            participants: result.isNewJoin ? item.participants + 1 : item.participants,
          }
        }),
      )

      if (result.isNewJoin) {
        message.success(`已加入 ${season.name}`)
      } else {
        message.info(`你已加入过 ${season.name}`)
      }

      setCurrentSeason(season.id)
      setCurrentAccount(result.accountId)
      navigate('/trading')
    } catch (error) {
      if (shouldFallbackToMockSeason(error)) {
        try {
          const fallback = await joinMockSeason({ seasonId: season.id, userId: currentUser.id })
          setSeasons((prev) => prev.map((item) => (item.id === season.id ? fallback.season : item)))
          setCurrentSeason(fallback.season.id)
          setCurrentAccount(null)
          message.warning('后端加入赛季接口暂不可用，已切换为 mock 加入模式')
          navigate('/trading')
          return
        } catch (fallbackError) {
          const fallbackText =
            fallbackError instanceof Error ? fallbackError.message : '加入赛季失败'
          message.error(fallbackText)
          return
        }
      }

      message.error(extractSeasonApiErrorMessage(error, '加入赛季失败'))
    } finally {
      setJoiningSeasonId(null)
    }
  }

  const onOpenCreate = (): void => {
    if (!ensureLogin()) {
      return
    }

    setIsCreateOpen(true)
    createForm.setFieldsValue({
      initialCash: 1000000,
      stockCount: 20,
    })
  }

  const onCreateSeason = async (): Promise<void> => {
    if (!currentUser) {
      return
    }

    const values = await createForm.validateFields()
    setIsCreating(true)

    try {
      const created = await createMockSeason({
        name: values.name.trim(),
        initialCash: values.initialCash,
        stockCount: values.stockCount,
        startDate: values.startDate,
        endDate: values.endDate,
        createdBy: currentUser.displayName,
        userId: currentUser.id,
      })

      setSeasons((prev) => [created, ...prev])
      setIsCreateOpen(false)
      createForm.resetFields()
      setFilter('all')
      message.success('赛季创建成功，已自动加入')
    } catch (error) {
      const text = error instanceof Error ? error.message : '创建赛季失败'
      message.error(text)
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Row justify="space-between" align="middle" gutter={[16, 16]}>
        <Col>
          <Typography.Title level={3} style={{ margin: 0 }}>
            赛季大厅
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            浏览赛季、加入比赛，或创建属于自己的模拟交易赛季。
          </Typography.Paragraph>
        </Col>
        <Col>
          <Space>
            <Button onClick={() => void loadSeasons()} loading={isLoading}>
              刷新
            </Button>
            <Button type="primary" onClick={onOpenCreate}>
              创建赛季
            </Button>
          </Space>
        </Col>
      </Row>

      {!currentUser && (
        <Alert
          type="info"
          showIcon
          message="当前未登录"
          description="你可以查看赛季列表；加入和创建赛季需要先登录。"
          action={
            <Button size="small" type="primary" onClick={() => navigate('/login')}>
              去登录
            </Button>
          }
        />
      )}

      <Row gutter={[12, 12]}>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="赛季总数" value={seasonStats.total} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="报名中" value={seasonStats.open} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="进行中" value={seasonStats.running} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="我已加入" value={seasonStats.joined} />
          </Card>
        </Col>
      </Row>

      <Card>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Row justify="space-between" align="middle" gutter={[12, 12]}>
            <Col>
              <Segmented
                value={filter}
                options={filterItems}
                onChange={(value) => setFilter(value as SeasonFilter)}
              />
            </Col>
            <Col>
              <Typography.Text type="secondary">当前展示：{filteredSeasons.length} 个赛季</Typography.Text>
            </Col>
          </Row>

          {errorMessage && (
            <Alert
              type="error"
              showIcon
              message={errorMessage}
              action={
                <Button size="small" onClick={() => void loadSeasons()}>
                  重试
                </Button>
              }
            />
          )}

          <Spin spinning={isLoading}>
            <List
              locale={{ emptyText: <Empty description="暂无可用赛季" /> }}
              dataSource={filteredSeasons}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button
                      key={`action-${item.id}`}
                      type={item.joined ? 'default' : 'primary'}
                      ghost={!item.joined}
                      disabled={item.status === '已结束' && !item.joined}
                      loading={joiningSeasonId === item.id}
                      onClick={() => void handleJoin(item)}
                    >
                      {item.joined ? '进入交易' : item.status === '已结束' ? '已结束' : '加入并进入'}
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space wrap>
                        <Typography.Text strong>{item.name}</Typography.Text>
                        <Tag color={statusColor[item.status]}>{item.status}</Tag>
                        {item.joined && <Badge status="success" text="已加入" />}
                      </Space>
                    }
                    description={
                      <Space size="large" wrap>
                        <Typography.Text type="secondary">参与人数：{item.participants}</Typography.Text>
                        <Typography.Text type="secondary">股票池：{item.stockCount} 支</Typography.Text>
                        <Typography.Text type="secondary">初始资金：¥{item.initialCash.toLocaleString()}</Typography.Text>
                        <Typography.Text type="secondary">
                          时间：{item.startDate} 至 {item.endDate}
                        </Typography.Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Spin>
        </Space>
      </Card>

      <Modal
        title="创建赛季"
        open={isCreateOpen}
        okText="创建"
        cancelText="取消"
        onCancel={() => {
          setIsCreateOpen(false)
          createForm.resetFields()
        }}
        onOk={() => void onCreateSeason()}
        confirmLoading={isCreating}
      >
        <Form<CreateSeasonFormValues>
          form={createForm}
          layout="vertical"
          initialValues={{
            initialCash: 1000000,
            stockCount: 20,
          }}
        >
          <Form.Item
            name="name"
            label="赛季名称"
            rules={[
              { required: true, message: '请输入赛季名称' },
              { min: 2, message: '赛季名称至少 2 个字符' },
            ]}
          >
            <Input placeholder="例如：S3 秋季赛" maxLength={30} />
          </Form.Item>

          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                name="initialCash"
                label="初始资金"
                rules={[{ required: true, message: '请输入初始资金' }]}
              >
                <InputNumber<number>
                  min={100000}
                  step={10000}
                  style={{ width: '100%' }}
                  formatter={(value) => `${value ?? ''}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                  parser={(value) => Number(String(value ?? '').replace(/,/g, ''))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="stockCount"
                label="股票池数量"
                rules={[{ required: true, message: '请输入股票池数量' }]}
              >
                <InputNumber<number> min={5} max={200} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                name="startDate"
                label="开始日期"
                rules={[{ required: true, message: '请选择开始日期' }]}
              >
                <Input type="date" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="endDate"
                label="结束日期"
                dependencies={['startDate']}
                rules={[
                  { required: true, message: '请选择结束日期' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      const startDate = getFieldValue('startDate')
                      if (!startDate || !value || value >= startDate) {
                        return Promise.resolve()
                      }
                      return Promise.reject(new Error('结束日期不能早于开始日期'))
                    },
                  }),
                ]}
              >
                <Input type="date" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </Space>
  )
}

export default LobbyPage
