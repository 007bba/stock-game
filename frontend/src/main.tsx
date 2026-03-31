import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import 'antd/dist/reset.css'
import './index.css'
import App from './App.tsx'
import HomePage from './pages/Home.tsx'
import LoginPage from './pages/Login.tsx'
import TradingPage from './pages/Trading.tsx'
import ReviewPage from './pages/Review.tsx'
import { AuthBootstrap, ProtectedRoute } from './components/AuthGuards.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN}>
      <AuthBootstrap>
        <BrowserRouter>
          <Routes>
            <Route element={<App />}>
              <Route index element={<HomePage />} />
              <Route path="/login" element={<LoginPage />} />
              <Route
                path="/train"
                element={
                  <ProtectedRoute>
                    <TradingPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/review"
                element={
                  <ProtectedRoute>
                    <ReviewPage />
                  </ProtectedRoute>
                }
              />
              <Route path="/lobby" element={<Navigate to="/" replace />} />
              <Route path="/trading" element={<Navigate to="/train" replace />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthBootstrap>
    </ConfigProvider>
  </StrictMode>,
)
