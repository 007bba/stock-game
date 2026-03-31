import { useState } from 'react'
import { Button, Card, Form, Input, InputNumber, Segmented, Space } from 'antd'

export type TradeSide = 'BUY' | 'SELL'

interface OrderFormValues {
  price: number
  qty: number
  reason: string
}

interface OrderFormProps {
  submitting?: boolean
  onSubmit?: (params: OrderFormValues & { side: TradeSide }) => void
}

function OrderForm({ submitting = false, onSubmit }: OrderFormProps) {
  const [side, setSide] = useState<TradeSide>('BUY')

  const handleFinish = (values: OrderFormValues): void => {
    onSubmit?.({ ...values, side })
  }

  return (
    <Card title="训练下单">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Segmented
          block
          value={side}
          options={[
            { label: '买入', value: 'BUY' },
            { label: '卖出', value: 'SELL' },
          ]}
          onChange={(value) => setSide(value as TradeSide)}
        />

        <Form<OrderFormValues> layout="vertical" onFinish={handleFinish} initialValues={{ qty: 100 }}>
          <Form.Item name="price" label="价格" rules={[{ required: true, message: '请输入价格' }]}>
            <InputNumber<number> min={0.01} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="qty" label="数量" rules={[{ required: true, message: '请输入数量' }]}>
            <InputNumber<number> min={100} step={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="reason"
            label="本次操作理由"
            rules={[
              { required: true, message: '请写下这次操作的理由' },
              { min: 6, message: '至少写 6 个字，避免无效记录' },
            ]}
          >
            <Input.TextArea
              rows={4}
              placeholder="例如：开盘后量价同步放大，回踩不破均线，按计划轻仓试错。"
              maxLength={140}
              showCount
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting} block>
            {side === 'BUY' ? '记录并买入' : '记录并卖出'}
          </Button>
        </Form>
      </Space>
    </Card>
  )
}

export default OrderForm
