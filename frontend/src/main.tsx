import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import 'antd/dist/reset.css'
import './index.css'
import App from './App.tsx'
import LoginPage from './pages/Login.tsx'
import LobbyPage from './pages/Lobby.tsx'
import TradingPage from './pages/Trading.tsx'
import { AuthBootstrap, ProtectedRoute } from './components/AuthGuards.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN}>
      <AuthBootstrap>
        <BrowserRouter>
          <Routes>
            <Route element={<App />}>
              <Route index element={<Navigate to="/lobby" replace />} />
              <Route path="/login" element={<LoginPage />} />
              <Route
                path="/lobby"
                element={
                  <ProtectedRoute>
                    <LobbyPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/trading"
                element={
                  <ProtectedRoute>
                    <TradingPage />
                  </ProtectedRoute>
                }
              />
            </Route>
            <Route path="*" element={<Navigate to="/lobby" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthBootstrap>
    </ConfigProvider>
  </StrictMode>,
)
