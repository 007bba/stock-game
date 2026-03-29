import { Card, Table, Tag } from 'antd'

export type OrderStatus =
  | 'PENDING'
  | 'PARTIAL'
  | 'FILLED'
  | 'CANCELED'
  | 'REJECTED'
  | 'EXPIRED'

export interface OrderItem {
  orderId: string
  tsCode: string
  side: 'BUY' | 'SELL'
  qty: number
  price: number
  status: OrderStatus
}

interface OrderListProps {
  orders: OrderItem[]
}

const statusColor: Record<OrderStatus, string> = {
  PENDING: 'processing',
  PARTIAL: 'warning',
  FILLED: 'success',
  CANCELED: 'default',
  REJECTED: 'error',
  EXPIRED: 'default',
}

const columns = [
  { title: '订单号', dataIndex: 'orderId', key: 'orderId' },
  { title: '股票', dataIndex: 'tsCode', key: 'tsCode' },
  { title: '方向', dataIndex: 'side', key: 'side' },
  { title: '数量', dataIndex: 'qty', key: 'qty' },
  { title: '价格', dataIndex: 'price', key: 'price' },
  {
    title: '状态',
    dataIndex: 'status',
    key: 'status',
    render: (status: OrderStatus) => <Tag color={statusColor[status]}>{status}</Tag>,
  },
]

function OrderList({ orders }: OrderListProps) {
  return (
    <Card title="委托 / 成交列表">
      <Table
        rowKey="orderId"
        size="small"
        pagination={false}
        columns={columns}
        dataSource={orders}
        scroll={{ x: 560 }}
      />
    </Card>
  )
}

export default OrderList
