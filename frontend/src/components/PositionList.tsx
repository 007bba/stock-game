import { Card, Table } from 'antd'

export interface PositionItem {
  tsCode: string
  qty: number
  avgPrice: number
  lastPrice?: number
}

interface PositionListProps {
  positions: PositionItem[]
}

const columns = [
  { title: '股票', dataIndex: 'tsCode', key: 'tsCode' },
  { title: '持仓', dataIndex: 'qty', key: 'qty' },
  { title: '成本', dataIndex: 'avgPrice', key: 'avgPrice' },
  { title: '现价', dataIndex: 'lastPrice', key: 'lastPrice' },
]

function PositionList({ positions }: PositionListProps) {
  return (
    <Card title="持仓列表">
      <Table
        rowKey="tsCode"
        size="small"
        pagination={false}
        columns={columns}
        dataSource={positions}
        scroll={{ x: 420 }}
      />
    </Card>
  )
}

export default PositionList
