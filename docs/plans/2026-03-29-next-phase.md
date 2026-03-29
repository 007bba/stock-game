# Stock Game 下一阶段任务规划（P7-P10）

- 文档日期：2026-03-29 13:05
- 当前状态：**MVP 后端已完成**，24/24 测试通过，CI/CD 已验证
- 目标：完成前端界面 + 用户认证 + 实时推送 + 生产部署

---

## 一、已完成回顾（MVP 后端）

### 已交付能力

| 模块 | 状态 | 说明 |
|------|------|------|
| 数据库 DDL | ✅ 95% | 核心交易、行情、账本、ETL 表已落地 |
| API 契约 | ✅ 90% | REST + WebSocket 事件模型已定义 |
| ETL 管道 | ✅ 93% | 支持 all/validate、降级、报告落盘 |
| 规则引擎 | ✅ 82% | T+1、涨跌停、停牌、批量撮合、账本更新 |
| 交易服务 | ✅ 100% | PgState 持久化、拒单码对齐、API 路由 |
| 测试覆盖 | ✅ 24/24 | 单元 + 集成 + 回放全量通过 |
| CI/CD | ✅ 100% | push 单测 + workflow_dispatch DB 集成 |

### 关键文件清单

```
scripts/
├── engine/
│   ├── state.py           # 订单状态机
│   ├── pg_state.py        # PostgreSQL 持久化
│   ├── matching.py        # 撮合引擎
│   └── orchestrator.py    # 事务编排器
├── service/
│   ├── api.py             # FastAPI 路由
│   ├── trading_service.py # 交易服务
│   ├── season_scheduler.py # 赛季调度器
│   ├── events.py          # 事件流
│   └── fill_market_ticks.py # 行情数据填充
└── etl/
    ├── tushare_pipeline.py # ETL 主流程
    └── validate_compression.py

tests/
├── engine/     # 引擎测试
├── service/    # 服务测试
├── etl/        # ETL 测试
└── integration/ # DB 集成测试

db/
└── schema.sql  # DDL 定义
```

---

## 二、下一阶段任务总览

| Phase | 任务 | 优先级 | 预计工时 | 依赖 |
|-------|------|--------|----------|------|
| P7 | 前端界面开发 | P0 | 3-4 天 | 无 |
| P8 | 用户认证系统 | P0 | 1 天 | P7 |
| P9 | WebSocket 实时推送 | P1 | 1-2 天 | P7 |
| P10 | 生产环境部署 | P1 | 1 天 | P8, P9 |
| P11 | 赛季管理与运营后台 | P2 | 2 天 | P10 |

---

## 三、Phase 7：前端界面开发

### 3.1 技术选型

- **框架**：React 18 + TypeScript + Vite
- **UI 库**：Ant Design 5.x
- **状态管理**：Zustand（轻量）
- **图表**：Lightweight Charts（K 线）
- **HTTP 客户端**：Axios

### 3.2 核心页面

| 页面 | 功能 | 优先级 |
|------|------|--------|
| 登录/注册 | 用户认证入口 | P0 |
| 赛季大厅 | 赛季列表、加入/创建 | P0 |
| 交易界面 | K 线、下单、持仓、订单簿 | P0 |
| 个人中心 | 资产、历史订单、排行榜 | P1 |
| 赛季详情 | 股票池、规则说明 | P2 |

### 3.3 交易界面核心组件

```
src/
├── pages/
│   ├── Login.tsx
│   ├── Lobby.tsx
│   └── Trading.tsx
├── components/
│   ├── KlineChart.tsx      # K 线图表
│   ├── OrderForm.tsx       # 下单表单
│   ├── OrderBook.tsx       # 订单簿
│   ├── PositionList.tsx    # 持仓列表
│   ├── OrderList.tsx       # 委托/成交列表
│   └── AccountInfo.tsx     # 账户信息
├── stores/
│   ├── authStore.ts
│   ├── tradingStore.ts
│   └── marketStore.ts
└── services/
    ├── api.ts              # HTTP 请求
    └── websocket.ts        # WebSocket 连接
```

### 3.4 任务拆分

- [ ] P7-T1：初始化 React 项目 + Vite + TypeScript
- [ ] P7-T2：集成 Ant Design + 路由配置
- [ ] P7-T3：实现登录/注册页面（mock 数据）
- [ ] P7-T4：实现赛季大厅页面
- [ ] P7-T5：实现交易界面布局（三栏式）
- [ ] P7-T6：集成 Lightweight Charts 绘制 K 线
- [ ] P7-T7：实现下单表单（买入/卖出 tab）
- [ ] P7-T8：实现订单簿组件（买卖盘）
- [ ] P7-T9：实现持仓列表组件
- [ ] P7-T10：实现委托/成交列表组件
- [ ] P7-T11：对接后端 API（替换 mock）
- [ ] P7-T12：响应式布局适配

---

## 四、Phase 8：用户认证系统

### 4.1 技术方案

**方案 A：Supabase Auth（推荐）**
- 优点：已有 Supabase 数据库，集成简单，支持多种登录方式
- 缺点：需要前端集成 Supabase SDK

**方案 B：自建 JWT**
- 优点：完全自主控制
- 缺点：需要额外开发用户表、密码加密、token 刷新

### 4.2 认证流程

```
用户注册/登录
    ↓
Supabase Auth 返回 JWT
    ↓
前端存储 token (localStorage)
    ↓
后续请求携带 Authorization: Bearer <token>
    ↓
后端验证 token + 获取 user_id
```

### 4.3 数据库变更

```sql
-- 用户表（如使用 Supabase Auth，此表自动创建）
CREATE TABLE auth.users (
    id UUID PRIMARY KEY,
    email VARCHAR(255),
    created_at TIMESTAMP
);

-- 账户表关联用户
ALTER TABLE accounts 
ADD COLUMN user_id UUID REFERENCES auth.users(id);
```

### 4.4 任务拆分

- [ ] P8-T1：启用 Supabase Auth 服务
- [ ] P8-T2：前端集成 Supabase JS SDK
- [ ] P8-T3：实现注册/登录/登出逻辑
- [ ] P8-T4：后端 API 集成 token 验证中间件
- [ ] P8-T5：账户创建流程（注册后自动创建初始账户）
- [ ] P8-T6：测试认证流程完整性

---

## 五、Phase 9：WebSocket 实时推送

### 5.1 推送内容

| 事件类型 | 数据 | 触发时机 |
|----------|------|----------|
| tick_update | { tick_id, prices, volume } | 每个 tick 撮合完成后 |
| order_matched | { order_id, qty, price } | 订单成交时 |
| order_rejected | { order_id, reject_code } | 订单被拒时 |
| position_update | { stock_code, qty, avg_price } | 持仓变更时 |
| account_update | { balance, total_asset } | 账户余额变更时 |

### 5.2 技术实现

**后端（FastAPI）**：
```python
from fastapi import WebSocket

@app.websocket("/ws/{season_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, season_id: int, user_id: str):
    await websocket.accept()
    # 订阅该赛季和用户的推送频道
    # 接收事件 -> 发送给客户端
```

**前端**：
```typescript
const ws = new WebSocket(`wss://api.example.com/ws/${seasonId}/${userId}`);
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // 更新 store -> 触发 UI 重渲染
};
```

### 5.3 任务拆分

- [ ] P9-T1：后端实现 WebSocket 路由
- [ ] P9-T2：实现事件发布/订阅机制（Redis Pub/Sub 或内存队列）
- [ ] P9-T3：撮合引擎集成事件推送
- [ ] P9-T4：前端 WebSocket 连接管理（重连、心跳）
- [ ] P9-T5：前端事件处理与 store 更新
- [ ] P9-T6：测试实时推送稳定性

---

## 六、Phase 10：生产环境部署

### 6.1 部署架构

```
用户
  ↓
Cloudflare CDN (静态资源)
  ↓
Supabase (数据库 + Auth)
  ↓
云托管服务 (FastAPI 后端)
  - Railway / Render / Fly.io
```

### 6.2 环境配置

| 环境 | 数据库 | API 域名 | 前端域名 |
|------|--------|----------|----------|
| 开发 | localhost | localhost:8000 | localhost:5173 |
| 生产 | Supabase | api.stockgame.com | stockgame.com |

### 6.3 部署清单

- [ ] P10-T1：后端 Dockerfile 编写
- [ ] P10-T2：云托管服务账号创建
- [ ] P10-T3：环境变量配置（DATABASE_URL, JWT_SECRET）
- [ ] P10-T4：前端构建 + CDN 部署
- [ ] P10-T5：域名解析配置
- [ ] P10-T6：HTTPS 证书配置
- [ ] P10-T7：生产环境测试

---

## 七、Phase 11：赛季管理与运营后台

### 11.1 管理功能

| 功能 | 说明 |
|------|------|
| 创建赛季 | 设置赛季参数、股票池 |
| 启动/暂停赛季 | 控制赛季状态 |
| 用户管理 | 查看用户列表、封禁 |
| 数据统计 | 活跃用户、交易量、排名 |
| 日志查看 | 系统日志、错误追踪 |

### 11.2 任务拆分

- [ ] P11-T1：设计管理后台页面结构
- [ ] P11-T2：实现赛季创建/编辑表单
- [ ] P11-T3：实现赛季调度控制（启动/暂停）
- [ ] P11-T4：实现用户列表与详情页
- [ ] P11-T5：实现数据统计面板
- [ ] P11-T6：权限控制（管理员角色）

---

## 八、硬约束

1. **DATABASE_URL** 禁止硬编码，仅从环境变量读取
2. **API 契约** 必须与 `docs/api/openapi.yaml` 保持一致
3. **所有 DB 写入** 必须在单事务内完成
4. **前端状态管理** 必须类型安全（TypeScript）
5. **WebSocket 连接** 必须支持断线重连
6. **生产环境** 必须启用 HTTPS

---

## 九、交付检查清单

### P7 完成标准

- [ ] 前端可运行 `npm run dev` 启动
- [ ] 交易界面可展示 K 线图表
- [ ] 下单表单可提交（对接 mock API）
- [ ] 订单簿可实时更新（mock 数据）

### P8 完成标准

- [ ] 用户可注册/登录
- [ ] JWT token 可正常验证
- [ ] 账户自动创建成功

### P9 完成标准

- [ ] WebSocket 连接稳定
- [ ] tick 事件可实时推送到前端
- [ ] 订单状态变更可实时更新

### P10 完成标准

- [ ] 生产环境可访问
- [ ] HTTPS 证书有效
- [ ] 数据库连接正常

---

## 十、交接提示词（给下一位 AI）

```
你现在接手 e:\stock-game 项目，MVP 后端已完成（24/24 测试通过，CI/CD 已验证）。

请阅读 docs/plans/2026-03-29-next-phase.md 了解下一阶段任务：
1. P7: 前端界面开发（React + TypeScript + Ant Design）
2. P8: 用户认证系统（Supabase Auth）
3. P9: WebSocket 实时推送
4. P10: 生产环境部署

当前优先级：
- 先完成 P7-T1：初始化 React 项目
- 然后按文档顺序推进

硬约束：
- DATABASE_URL 禁止硬编码
- API 契约与 openapi.yaml 保持一致
- DB 写入单事务
- 前端类型安全（TypeScript）

建议从 P7-T1 开始，初始化前端项目结构。
```

---

## 十一、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Supabase 连接池限制 | 并发高峰可能超时 | 使用事务时快速释放连接 |
| WebSocket 连接数限制 | 高并发时可能断开 | 实现断线重连 + 心跳 |
| 前端构建体积过大 | 首屏加载慢 | 代码分割 + 懒加载 |
| 跨域问题 | 前后端分离部署时阻塞 | 配置 CORS 中间件 |
