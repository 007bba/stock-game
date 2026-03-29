import { Card, Col, Row, Table } from 'antd'

export interface OrderBookLevel {
  price: number
  qty: number
}

interface OrderBookProps {
  bids: OrderBookLevel[]
  asks: OrderBookLevel[]
}

const columns = [
  { title: '价格', dataIndex: 'price', key: 'price' },
  { title: '数量', dataIndex: 'qty', key: 'qty' },
]

function OrderBook({ bids, asks }: OrderBookProps) {
  return (
    <Card title="订单簿">
      <Row gutter={12}>
        <Col span={12}>
          <Table
            rowKey="price"
            size="small"
            pagination={false}
            columns={columns}
            dataSource={bids}
            scroll={{ x: 180 }}
          />
        </Col>
        <Col span={12}>
          <Table
            rowKey="price"
            size="small"
            pagination={false}
            columns={columns}
            dataSource={asks}
            scroll={{ x: 180 }}
          />
        </Col>
      </Row>
    </Card>
  )
}

export default OrderBook
