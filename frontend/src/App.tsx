import { Layout, Menu, Space, Tag, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import './App.css'

const menuItems: MenuProps['items'] = [
  { key: '/', label: '首页' },
  { key: '/train', label: '训练' },
  { key: '/review', label: '复盘' },
  { key: '/login', label: '登录' },
]

function getSelectedMenuKey(pathname: string): string {
  if (pathname.startsWith('/train') || pathname.startsWith('/trading')) {
    return '/train'
  }
  if (pathname.startsWith('/review')) {
    return '/review'
  }
  if (pathname.startsWith('/login')) {
    return '/login'
  }
  return '/'
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
          <Tag color="gold">v2</Tag>
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
