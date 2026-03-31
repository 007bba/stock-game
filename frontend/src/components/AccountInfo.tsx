import { Card, Space, Statistic } from 'antd'

interface AccountInfoProps {
  availableCash: number
  totalAsset: number
}

function AccountInfo({ availableCash, totalAsset }: AccountInfoProps) {
  return (
    <Card title="训练资金">
      <Space size="large" wrap>
        <Statistic title="可用资金" value={availableCash} precision={2} />
        <Statistic title="总资产" value={totalAsset} precision={2} />
      </Space>
    </Card>
  )
}

export default AccountInfo
