import { Layout, Menu, Space, Tag, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import './App.css'

const menuItems: MenuProps['items'] = [
  { key: '/login', label: '登录' },
  { key: '/lobby', label: '赛季大厅' },
  { key: '/trading', label: '交易界面' },
]

function getSelectedMenuKey(pathname: string): string {
  if (pathname.startsWith('/trading')) {
    return '/trading'
  }
  if (pathname.startsWith('/login')) {
    return '/login'
  }
  return '/lobby'
}

function App() {
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <Layout className="app-shell">
      <Layout.Header className="app-header">
        <Space size="middle" className="app-brand">
          <Typography.Text strong className="app-title">
            Stock Game
          </Typography.Text>
          <Tag color="gold">P9</Tag>
        </Space>
        <Menu
          mode="horizontal"
          theme="dark"
          selectedKeys={[getSelectedMenuKey(location.pathname)]}
          items={menuItems}
          onClick={(menu) => navigate(String(menu.key))}
          className="app-menu"
        />
      </Layout.Header>
      <Layout.Content className="app-content">
        <Outlet />
      </Layout.Content>
    </Layout>
  )
}

export default App
