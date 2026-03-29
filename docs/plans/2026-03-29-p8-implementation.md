# P8 用户认证系统实施计划

- 文档日期：2026-03-29 18:50
- 阶段：P8 - 用户认证系统
- 优先级：P0
- 预计工时：1 天
- 依赖：P7 前端界面完成

---

## 一、目标

将当前 mock 登录态替换为 Supabase Auth 真实认证，实现：
1. 用户注册/登录/登出
2. JWT token 管理
3. 后端 API token 验证
4. 用户账户自动创建

---

## 二、技术方案

### 2.1 架构设计

```
前端 (React)
    ↓ Supabase JS SDK
Supabase Auth
    ↓ 返回 JWT token
前端存储 token (localStorage)
    ↓ HTTP 请求携带 Authorization: Bearer <token>
后端 (FastAPI)
    ↓ 验证 token + 获取 user_id
业务逻辑
```

### 2.2 Supabase Auth 配置

**已启用 Supabase 项目**：`db.oszikuwftdlsnjkheczh.supabase.co`

**认证方式**：
- Email/Password（主要）
- 匿名登录（可选，后续）
- OAuth（可选，后续）

**Token 格式**：JWT（包含 `sub` = user_id, `email` 等）

### 2.3 数据库变更

```sql
-- Supabase Auth 自动创建 auth.users 表
-- 当前 schema 的 accounts 表已经是 season_id + user_id 维度
-- 因此 P8 采用：注册仅创建 auth.users 用户，不立即创建 accounts
-- 在“加入赛季”动作中单事务创建 accounts 行（幂等）
```

---

## 三、任务拆分

### P8-T1：启用 Supabase Auth 服务

**操作步骤**：

1. 登录 Supabase Dashboard
   - 访问：https://supabase.com/dashboard
   - 选择项目：`db.oszikuwftdlsnjkheczh`

2. 启用 Email Auth
   - Authentication → Providers → Email
   - Enable Email provider
   - 配置：Enable email confirmations = false（MVP 阶段简化）

3. 获取配置信息
   - Settings → API
  - 记录：`URL`、`anon` key、`JWT Secret`

4. 本地环境变量映射
  - 前端：`frontend/.env.local` 中配置 `VITE_SUPABASE_URL`、`VITE_SUPABASE_ANON_KEY`
  - 后端：根目录 `.env` 中配置 `SUPABASE_URL`、`SUPABASE_JWT_SECRET`
  - 严禁把 `SUPABASE_JWT_SECRET` 写入代码或提交到仓库

**验证方式**：
- Dashboard 中看到 Email provider 已启用
- 本地环境文件配置完成（可参考 `.env.example` 与 `frontend/.env.example`）

---

### P8-T2：前端集成 Supabase JS SDK

**操作步骤**：

1. 安装依赖
   ```bash
   cd frontend
   npm install @supabase/supabase-js
   ```

2. 创建 Supabase 客户端配置
   ```typescript
  // frontend/src/services/supabase.ts
   import { createClient } from '@supabase/supabase-js'
   
   const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
   const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY
   
   export const supabase = createClient(supabaseUrl, supabaseAnonKey)
   ```

3. 配置环境变量
   ```bash
   # frontend/.env.local
   VITE_SUPABASE_URL=https://db.oszikuwftdlsnjkheczh.supabase.co
   VITE_SUPABASE_ANON_KEY=<your-anon-key>
   ```

4. 更新 authStore
   ```typescript
   // frontend/src/stores/authStore.ts
   import { create } from 'zustand'
  import { supabase } from '../services/supabase'
   
   interface AuthState {
     user: any | null
     session: any | null
     loading: boolean
     signUp: (email: string, password: string) => Promise<void>
     signIn: (email: string, password: string) => Promise<void>
     signOut: () => Promise<void>
     getSession: () => Promise<void>
   }
   
   export const useAuthStore = create<AuthState>((set) => ({
     user: null,
     session: null,
     loading: true,
     
     signUp: async (email, password) => {
       const { data, error } = await supabase.auth.signUp({
         email,
         password,
       })
       if (error) throw error
       set({ user: data.user, session: data.session })
     },
     
     signIn: async (email, password) => {
       const { data, error } = await supabase.auth.signInWithPassword({
         email,
         password,
       })
       if (error) throw error
       set({ user: data.user, session: data.session })
     },
     
     signOut: async () => {
       const { error } = await supabase.auth.signOut()
       if (error) throw error
       set({ user: null, session: null })
     },
     
     getSession: async () => {
       const { data: { session } } = await supabase.auth.getSession()
       set({ session, user: session?.user ?? null, loading: false })
     },
   }))
   ```

**验证方式**：
- `npm run dev` 无报错
- 可以调用 `supabase.auth.signUp`

---

### P8-T3：实现注册/登录/登出逻辑

**操作步骤**：

1. 更新 Login.tsx
   ```typescript
   // frontend/src/pages/Login.tsx
   import { useAuthStore } from '../stores/authStore'
   
   const Login = () => {
     const { signIn, signUp } = useAuthStore()
     
     const handleLogin = async (email: string, password: string) => {
       try {
         await signIn(email, password)
         message.success('登录成功')
         navigate('/lobby')
       } catch (error) {
         message.error('登录失败：' + error.message)
       }
     }
     
     const handleRegister = async (email: string, password: string) => {
       try {
         await signUp(email, password)
         message.success('注册成功，请登录')
       } catch (error) {
         message.error('注册失败：' + error.message)
       }
     }
     
     // ... UI 代码
   }
   ```

2. 添加全局认证检查
   ```typescript
   // frontend/src/App.tsx
   useEffect(() => {
     const { getSession } = useAuthStore.getState()
     getSession()
   }, [])
   ```

3. 添加路由守卫
   ```typescript
   // frontend/src/App.tsx
   const PrivateRoute = ({ children }: { children: React.ReactNode }) => {
     const { user, loading } = useAuthStore()
     
     if (loading) return <div>Loading...</div>
     if (!user) return <Navigate to="/login" />
     
     return <>{children}</>
   }
   ```

**验证方式**：
- 可以注册新用户
- 可以登录已注册用户
- 登录后跳转到赛季大厅
- 未登录访问 `/lobby` 或 `/trading` 被重定向到 `/login`

---

### P8-T4：后端 API 集成 token 验证中间件

**操作步骤**：

1. 安装依赖
   ```bash
   pip install python-jose[cryptography] httpx
   ```

2. 创建验证中间件
   ```python
   # scripts/service/auth.py
   from fastapi import Depends, HTTPException, status
   from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
   from jose import jwt, JWTError
   import httpx
   import os
   
   security = HTTPBearer()
   
   SUPABASE_URL = os.getenv("SUPABASE_URL")
   SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
   
   async def get_current_user(
       credentials: HTTPAuthorizationCredentials = Depends(security)
   ):
       token = credentials.credentials
       
       try:
           # 验证 JWT
           payload = jwt.decode(
               token,
               SUPABASE_JWT_SECRET,
               algorithms=["HS256"],
               audience="authenticated"
           )
           user_id = payload.get("sub")
           if user_id is None:
               raise HTTPException(status_code=401, detail="Invalid token")
           
           return {"user_id": user_id, "email": payload.get("email")}
       
       except JWTError:
           raise HTTPException(
               status_code=status.HTTP_401_UNAUTHORIZED,
               detail="Could not validate credentials",
               headers={"WWW-Authenticate": "Bearer"},
           )
   ```

3. 应用到 API 路由
   ```python
   # scripts/service/api.py
   from .auth import get_current_user
   
   @app.post("/api/orders")
   async def place_order(
       order: PlaceOrderRequest,
       user = Depends(get_current_user)
   ):
       user_id = user["user_id"]
       # 业务逻辑
   ```

**验证方式**：
- 无 token 请求返回 401
- 有效 token 请求成功
- 过期 token 返回 401

---

### P8-T5：账户创建流程

**操作步骤**：

1. 创建 Supabase 触发器
   ```sql
   -- 在 Supabase SQL Editor 中执行
   
   -- 创建函数：用户注册时自动创建账户
   CREATE OR REPLACE FUNCTION public.handle_new_user()
   RETURNS TRIGGER AS $$
   BEGIN
     INSERT INTO public.accounts (user_id, balance, total_asset, created_at)
     VALUES (NEW.id, 1000000.00, 1000000.00, NOW());
     RETURN NEW;
   END;
   $$ LANGUAGE plpgsql SECURITY DEFINER;
   
   -- 创建触发器
   CREATE TRIGGER on_auth_user_created
     AFTER INSERT ON auth.users
     FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
   ```

2. 更新 accounts 表结构
   ```sql
   -- 确保 user_id 字段存在
   ALTER TABLE accounts 
   ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
   
   CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id);
   ```

**验证方式**：
- 注册新用户后，`accounts` 表自动新增一条记录
- 初始资金为 100 万

---

### P8-T6：测试认证流程完整性

**测试用例**：

```bash
# 1. 注册新用户
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "password123"}'

# 2. 登录获取 token
curl -X POST http://localhost:8000/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "password123"}'

# 3. 使用 token 访问 API
curl -X GET http://localhost:8000/api/orders \
  -H "Authorization: Bearer <token>"

# 4. 验证账户自动创建
psql -c "SELECT * FROM accounts WHERE user_id = '<user_id>'"
```

**前端测试**：
- 注册 → 登录 → 访问赛季大厅 → 下单（携带 token）

**验证方式**：
- 所有测试用例通过
- 无认证相关的 500 错误

---

## 四、硬约束

1. **SUPABASE_JWT_SECRET** 必须从环境变量读取，禁止硬编码
2. **Token 验证** 必须验证 `audience` 字段
3. **账户创建** 必须使用事务，保证原子性
4. **前端 token 存储** 必须使用 `localStorage`（MVP 阶段，后续可迁移到 HttpOnly Cookie）

---

## 五、环境变量清单

| 变量名 | 位置 | 说明 |
|--------|------|------|
| `VITE_SUPABASE_URL` | frontend/.env.local | Supabase 项目 URL |
| `VITE_SUPABASE_ANON_KEY` | frontend/.env.local | Supabase anon key |
| `SUPABASE_URL` | 后端环境变量 | 同上 |
| `SUPABASE_JWT_SECRET` | 后端环境变量 | JWT 密钥（从 Supabase Dashboard 获取） |

**获取 JWT Secret**：
1. Supabase Dashboard → Settings → API
2. 找到 `JWT Secret` 字段
3. 配置到后端环境变量

---

## 六、文件清单

**新增文件**：
```
frontend/src/lib/supabase.ts     # Supabase 客户端
frontend/src/lib/auth.ts         # 认证工具函数
scripts/service/auth.py          # 后端认证中间件
```

**修改文件**：
```
frontend/src/stores/authStore.ts      # 集成 Supabase Auth
frontend/src/pages/Login.tsx          # 替换 mock 登录
frontend/src/App.tsx                  # 添加路由守卫
frontend/src/services/api.ts          # 携带 token
scripts/service/api.py                # 应用认证中间件
db/schema.sql                         # accounts 表添加 user_id
```

---

## 七、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Supabase Auth 服务不可用 | 无法登录 | 本地 mock 降级方案 |
| JWT Secret 泄露 | 安全风险 | 仅从环境变量读取，不提交代码 |
| Token 过期时间太短 | 频繁登出 | Supabase 默认 1 小时，可配置刷新 |
| 用户重复注册 | 数据冗余 | Supabase Auth 自动去重 |

---

## 八、交付检查清单

- [ ] Supabase Auth Email provider 已启用
- [ ] 前端可注册/登录/登出
- [ ] 前端 token 存储正常
- [ ] 后端 token 验证正常
- [ ] 用户注册后账户自动创建
- [ ] 前端携带 token 调用后端 API 成功
- [ ] 未登录访问保护路由被重定向
- [ ] 环境变量配置正确

---

## 九、交接提示词（给下一位 AI）

```
你现在接手 e:\stock-game 项目，P7 前端界面已完成，现在进入 P8 用户认证系统阶段。

请阅读 docs/plans/2026-03-29-p8-implementation.md 了解详细任务：
1. P8-T1: 启用 Supabase Auth 服务
2. P8-T2: 前端集成 Supabase JS SDK
3. P8-T3: 实现注册/登录/登出逻辑
4. P8-T4: 后端 API 集成 token 验证中间件
5. P8-T5: 账户创建流程
6. P8-T6: 测试认证流程完整性

当前优先级：先完成 P8-T1（启用 Supabase Auth）

硬约束：
- SUPABASE_JWT_SECRET 禁止硬编码
- Token 验证必须验证 audience
- 账户创建必须单事务

技术栈：
- 前端：@supabase/supabase-js
- 后端：python-jose + FastAPI Depends
- 数据库：Supabase Auth + PostgreSQL 触发器

建议从 P8-T1 开始，先在 Supabase Dashboard 启用 Email Auth。
```
