import { useMemo } from 'react'
import { Alert, Button, Card, Checkbox, Form, Input, Space, Tabs, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'

interface AuthFormValues {
  email: string
  password: string
  displayName?: string
  confirmPassword?: string
  remember?: boolean
}

function LoginPage() {
  const navigate = useNavigate()
  const [form] = Form.useForm<AuthFormValues>()

  const {
    mode,
    currentUser,
    isLoading,
    errorMessage,
    setMode,
    clearError,
    login,
    register,
    logout,
  } = useAuthStore((state) => state)

  const modeItems = useMemo(
    () => [
      { key: 'login', label: '登录' },
      { key: 'register', label: '注册' },
    ],
    [],
  )

  const isRegisterMode = mode === 'register'

  const onFinish = async (values: AuthFormValues) => {
    try {
      if (isRegisterMode) {
        const result = await register({
          email: values.email,
          password: values.password,
          displayName: values.displayName,
          remember: values.remember ?? true,
        })

        if (result.needsEmailConfirmation) {
          message.info('注册成功，请先完成邮箱确认后再登录')
          return
        }

        message.success('注册成功，已自动登录')
      } else {
        await login({
          email: values.email,
          password: values.password,
          remember: values.remember ?? false,
        })
        message.success('登录成功')
      }

      navigate('/lobby')
    } catch {
      // 错误信息由 store 维护并展示在页面 Alert
    }
  }

  const onModeChange = (activeKey: string) => {
    clearError()
    setMode(activeKey as 'login' | 'register')
    form.resetFields(['password', 'confirmPassword'])
  }

  if (currentUser) {
    return (
      <Card title="认证状态" style={{ maxWidth: 560, margin: '0 auto' }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Alert
            type="success"
            showIcon
            message={`当前已登录：${currentUser.displayName}`}
            description={`邮箱：${currentUser.email}`}
          />
          <Space>
            <Button type="primary" onClick={() => navigate('/lobby')}>
              进入赛季大厅
            </Button>
            <Button
              onClick={async () => {
                try {
                  await logout()
                  message.info('已退出登录')
                } catch {
                  // 错误信息由 store 维护并展示在页面 Alert
                }
              }}
            >
              退出登录
            </Button>
          </Space>
        </Space>
      </Card>
    )
  }

  return (
    <Card title="登录 / 注册" style={{ maxWidth: 560, margin: '0 auto' }}>
      <Typography.Paragraph type="secondary">
        当前为 Supabase Auth 认证流程，登录后可访问赛季大厅和交易界面。
      </Typography.Paragraph>

      <Tabs activeKey={mode} items={modeItems} onChange={onModeChange} />

      {errorMessage && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={errorMessage}
          closable
          onClose={() => clearError()}
        />
      )}

      <Form<AuthFormValues>
        form={form}
        layout="vertical"
        onFinish={onFinish}
        initialValues={{ remember: mode === 'register' }}
      >
        {isRegisterMode && (
          <Form.Item
            label="昵称"
            name="displayName"
            rules={[{ required: true, message: '请输入昵称' }]}
          >
            <Input placeholder="例如：AlphaTrader" maxLength={24} />
          </Form.Item>
        )}

        <Form.Item
          label="邮箱"
          name="email"
          rules={[
            { required: true, message: '请输入邮箱' },
            { type: 'email', message: '邮箱格式不正确' },
          ]}
        >
          <Input placeholder="you@example.com" />
        </Form.Item>

        <Form.Item
          label="密码"
          name="password"
          rules={[
            { required: true, message: '请输入密码' },
            { min: 6, message: '密码至少 6 位' },
          ]}
        >
          <Input.Password placeholder="请输入密码" />
        </Form.Item>

        {isRegisterMode && (
          <Form.Item
            label="确认密码"
            name="confirmPassword"
            dependencies={['password']}
            rules={[
              { required: true, message: '请再次输入密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('两次输入的密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password placeholder="请再次输入密码" />
          </Form.Item>
        )}

        <Form.Item name="remember" valuePropName="checked">
          <Checkbox>记住登录状态</Checkbox>
        </Form.Item>

        <Space size="middle" style={{ width: '100%', justifyContent: 'space-between' }}>
          <Button
            onClick={() => {
              form.setFieldsValue({
                email: 'demo@stock-game.local',
                password: '123456',
                confirmPassword: '123456',
                displayName: 'DemoPlayer',
              })
            }}
          >
            填充演示账号
          </Button>
          <Space>
            <Button type="primary" htmlType="submit" loading={isLoading}>
              {isRegisterMode ? '注册并登录' : '登录'}
            </Button>
          </Space>
        </Space>
      </Form>
    </Card>
  )
}

export default LoginPage
