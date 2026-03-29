# P9 WebSocket 实时推送实施计划

- 文档日期：2026-03-29 20:28
- 阶段：P9 - WebSocket 实时推送
- 优先级：P1
- 预计工时：1-2 天
- 依赖：P8 用户认证完成

---

## 一、目标

让交易界面实时更新，无需手动刷新：
1. 每个 tick 推送最新行情
2. 订单成交/拒单实时通知
3. 持仓自动更新
4. 订单簿实时刷新

---

## 二、技术方案

### 2.1 架构设计

```
撮合引擎处理 tick
    ↓
生成事件 (tick_update, order_matched, etc.)
    ↓
发布到事件队列 (内存队列/Redis)
    ↓
WebSocket 连接管理器广播
    ↓
前端 WebSocket 接收
    ↓
更新 store → UI 重渲染
```

### 2.2 事件类型

| 事件类型 | 数据结构 | 触发时机 |
|----------|----------|----------|
| `tick_update` | `{ tickId, seasonId, gameDay, tickIndex }` | 每个 tick 撮合完成 |
| `order_matched` | `{ orderId, accountId, qty, price }` | 订单成交 |
| `order_rejected` | `{ orderId, rejectCode, rejectReason }` | 订单被拒 |
| `position_update` | `{ tsCode, qty, avgPrice }` | 持仓变更 |
| `account_update` | `{ balance, totalAsset }` | 账户余额变更 |
| `quote_update` | `{ tsCode, open, high, low, close, volume }` | 行情更新 |

### 2.3 WebSocket 路由设计

**连接端点：**
```
ws://localhost:8000/ws/{seasonId}?token={jwt_token}
```

**认证方式：**
- 连接时通过 query param 传递 JWT token
- 后端验证 token 后建立连接
- 每个 WebSocket 连接绑定一个 seasonId 和 userId

**订阅机制：**
- 用户自动订阅自己所在赛季的事件
- 只接收与自己相关的订单、持仓更新
- tick_update 和 quote_update 广播给该赛季所有用户

---

## 三、任务拆分

### P9-T1：后端 WebSocket 路由（2h）

**目标**：实现 WebSocket 连接、认证、断线处理

**操作步骤**：

1. 创建 WebSocket 连接管理器
   ```python
   # scripts/service/websocket_manager.py
   from fastapi import WebSocket
   from typing import Dict, Set
   
   class ConnectionManager:
       def __init__(self):
           # season_id -> set of websocket connections
           self.active_connections: Dict[int, Set[WebSocket]] = {}
           # websocket -> user info
           self.connection_user_map: Dict[WebSocket, dict] = {}
       
       async def connect(self, websocket: WebSocket, season_id: int, user_id: str):
           await websocket.accept()
           if season_id not in self.active_connections:
               self.active_connections[season_id] = set()
           self.active_connections[season_id].add(websocket)
           self.connection_user_map[websocket] = {
               "season_id": season_id,
               "user_id": user_id,
           }
       
       def disconnect(self, websocket: WebSocket):
           user_info = self.connection_user_map.get(websocket)
           if user_info:
               season_id = user_info["season_id"]
               self.active_connections[season_id].discard(websocket)
           self.connection_user_map.pop(websocket, None)
       
       async def broadcast_to_season(self, season_id: int, message: dict):
           if season_id in self.active_connections:
               for connection in self.active_connections[season_id]:
                   await connection.send_json(message)
       
       async def send_to_user(self, user_id: str, message: dict):
           for ws, info in self.connection_user_map.items():
               if info["user_id"] == user_id:
                   await ws.send_json(message)
   ```

2. 添加 WebSocket 路由
   ```python
   # scripts/service/api.py
   from fastapi import WebSocket, WebSocketDisconnect
   from scripts.service.websocket_manager import manager
   from scripts.service.auth import get_current_user_ws
   
   @app.websocket("/ws/{seasonId}")
   async def websocket_endpoint(websocket: WebSocket, seasonId: int, token: str):
       # 验证 token
       user = await get_current_user_ws(token)
       if not user:
           await websocket.close(code=4001, reason="Unauthorized")
           return
       
       await manager.connect(websocket, seasonId, user.user_id)
       try:
           while True:
               # 保持连接，接收心跳
               data = await websocket.receive_text()
               if data == "ping":
                   await websocket.send_text("pong")
       except WebSocketDisconnect:
           manager.disconnect(websocket)
   ```

3. 实现 WebSocket 认证
   ```python
   # scripts/service/auth.py
   async def get_current_user_ws(token: str) -> AuthContext | None:
       # 复用 JWT 验证逻辑
       try:
           # ... JWT 验证代码
           return AuthContext(user_id=sub, email=email, claims=payload)
       except:
           return None
   ```

**验证方式**：
- 用 WebSocket 客户端工具测试连接
- 无 token 连接被拒绝
- 有效 token 连接成功

---

### P9-T2：事件发布/订阅机制（1h）

**目标**：在撮合引擎中集成事件发布

**操作步骤**：

1. 创建事件发布器
   ```python
   # scripts/service/event_publisher.py
   from scripts.service.websocket_manager import manager
   import asyncio
   
   class EventPublisher:
       def __init__(self, ws_manager: manager):
           self.manager = ws_manager
       
       async def publish_tick_update(self, season_id: int, tick_data: dict):
           await self.manager.broadcast_to_season(season_id, {
               "type": "tick_update",
               "data": tick_data,
           })
       
       async def publish_order_matched(self, user_id: str, order_data: dict):
           await self.manager.send_to_user(user_id, {
               "type": "order_matched",
               "data": order_data,
           })
       
       async def publish_position_update(self, user_id: str, position_data: dict):
           await self.manager.send_to_user(user_id, {
               "type": "position_update",
               "data": position_data,
           })
   ```

2. 集成到交易服务
   ```python
   # scripts/service/trading_service.py
   class TradingService:
       def __init__(self, state, event_publisher=None):
           self.state = state
           self.event_publisher = event_publisher
       
       def place_order(self, tick, quote, req):
           order = self.orchestrator.place_order(...)
           
           # 发布订单事件
           if self.event_publisher and order.status == "matched":
               asyncio.create_task(
                   self.event_publisher.publish_order_matched(
                       user_id=req.user_id,
                       order_data=self._order_to_dto(order),
                   )
               )
           
           return self._order_to_dto(order)
   ```

**验证方式**：
- 下单后检查 WebSocket 客户端是否收到事件

---

### P9-T3：撮合引擎集成事件推送（1h）

**目标**：在 `process_tick` 中发布 tick_update 事件

**操作步骤**：

1. 修改 `TradingService.process_tick`
   ```python
   def process_tick(self, tick, quotes_by_code):
       trade_ids = self.orchestrator.process_tick(tick, quotes_by_code)
       
       # 发布 tick 事件
       if self.event_publisher:
           asyncio.create_task(
               self.event_publisher.publish_tick_update(
                   season_id=tick.season_id,
                   tick_data={
                       "tickId": tick.id,
                       "gameDay": tick.game_day,
                       "tickIndex": tick.tick_index,
                       "tradeCount": len(trade_ids),
                   }
               )
           )
       
       return {...}
   ```

**验证方式**：
- 调用 `process_tick` 后检查 WebSocket 客户端

---

### P9-T4：前端 WebSocket 连接管理（2h）

**目标**：前端建立 WebSocket 连接，处理重连、心跳

**操作步骤**：

1. 创建 WebSocket 服务
   ```typescript
   // frontend/src/services/websocketClient.ts
   export class WebSocketClient {
     private ws: WebSocket | null = null
     private reconnectAttempts = 0
     private maxReconnectAttempts = 5
     private reconnectDelay = 1000
     private pingInterval: number | null = null
     
     constructor(
       private url: string,
       private onMessage: (data: any) => void,
     ) {}
     
     connect(): void {
       this.ws = new WebSocket(this.url)
       
       this.ws.onopen = () => {
         console.log('WebSocket connected')
         this.reconnectAttempts = 0
         this.startHeartbeat()
       }
       
       this.ws.onmessage = (event) => {
         const data = JSON.parse(event.data)
         this.onMessage(data)
       }
       
       this.ws.onclose = () => {
         this.stopHeartbeat()
         this.scheduleReconnect()
       }
       
       this.ws.onerror = (error) => {
         console.error('WebSocket error:', error)
       }
     }
     
     private startHeartbeat(): void {
       this.pingInterval = window.setInterval(() => {
         if (this.ws?.readyState === WebSocket.OPEN) {
           this.ws.send('ping')
         }
       }, 30000)
     }
     
     private stopHeartbeat(): void {
       if (this.pingInterval) {
         clearInterval(this.pingInterval)
         this.pingInterval = null
       }
     }
     
     private scheduleReconnect(): void {
       if (this.reconnectAttempts < this.maxReconnectAttempts) {
         setTimeout(() => {
           this.reconnectAttempts++
           this.connect()
         }, this.reconnectDelay * Math.pow(2, this.reconnectAttempts))
       }
     }
     
     disconnect(): void {
       this.stopHeartbeat()
       this.ws?.close()
       this.ws = null
     }
   }
   ```

2. 创建 WebSocket hook
   ```typescript
   // frontend/src/hooks/useWebSocket.ts
   import { useEffect, useRef } from 'react'
   import { useAuthStore } from '../stores/authStore'
   import { useTradingStore } from '../stores/tradingStore'
   import { WebSocketClient } from '../services/websocketClient'
   
   export function useWebSocket() {
     const wsRef = useRef<WebSocketClient | null>(null)
     const token = useAuthStore((s) => s.session?.access_token)
     const seasonId = useTradingStore((s) => s.currentSeasonId)
     
     useEffect(() => {
       if (!token || !seasonId) return
       
       const wsUrl = `${import.meta.env.VITE_WS_BASE_URL}/ws/${seasonId}?token=${token}`
       wsRef.current = new WebSocketClient(wsUrl, (data) => {
         // 处理事件
         handleWebSocketMessage(data)
       })
       wsRef.current.connect()
       
       return () => {
         wsRef.current?.disconnect()
       }
     }, [token, seasonId])
     
     return wsRef.current
   }
   
   function handleWebSocketMessage(data: any) {
     switch (data.type) {
       case 'tick_update':
         // 更新 tick 状态
         break
       case 'order_matched':
         // 更新订单状态
         break
       case 'position_update':
         // 更新持仓
         break
     }
   }
   ```

**验证方式**：
- 前端控制台显示 "WebSocket connected"
- 断网后自动重连

---

### P9-T5：前端事件处理与 store 更新（2h）

**目标**：WebSocket 事件触发 store 更新

**操作步骤**：

1. 更新 tradingStore
   ```typescript
   // frontend/src/stores/tradingStore.ts
   interface TradingState {
     // ... 现有字段
     orders: Order[]
     positions: Position[]
     addOrder: (order: Order) => void
     updateOrder: (orderId: number, updates: Partial<Order>) => void
     updatePosition: (tsCode: string, updates: Partial<Position>) => void
   }
   
   export const useTradingStore = create<TradingState>((set) => ({
     // ...
     addOrder: (order) => set((state) => ({
       orders: [...state.orders, order],
     })),
     updateOrder: (orderId, updates) => set((state) => ({
       orders: state.orders.map((o) =>
         o.id === orderId ? { ...o, ...updates } : o
       ),
     })),
     updatePosition: (tsCode, updates) => set((state) => ({
       positions: state.positions.map((p) =>
         p.tsCode === tsCode ? { ...p, ...updates } : p
       ),
     })),
   }))
   ```

2. 实现 handleWebSocketMessage
   ```typescript
   function handleWebSocketMessage(data: any) {
     const { type, data: eventData } = data
     
     switch (type) {
       case 'order_matched':
         useTradingStore.getState().updateOrder(eventData.id, {
           status: 'filled',
           filledQty: eventData.filledQty,
           avgPrice: eventData.avgPrice,
         })
         break
       
       case 'position_update':
         useTradingStore.getState().updatePosition(eventData.tsCode, {
           qty: eventData.qty,
           avgPrice: eventData.avgPrice,
         })
         break
       
       case 'account_update':
         useTradingStore.getState().updateAccount({
           balance: eventData.balance,
           totalAsset: eventData.totalAsset,
         })
         break
     }
   }
   ```

**验证方式**：
- 下单后持仓自动更新
- 订单状态实时变化

---

## 四、硬约束

1. **WebSocket 认证** 必须验证 JWT token
2. **断线重连** 必须自动重连，最多 5 次
3. **心跳机制** 每 30 秒发送 ping
4. **事件幂等** 相同事件重复接收不破坏状态

---

## 五、文件清单

**新增文件**：
```
scripts/service/websocket_manager.py     # WebSocket 连接管理
scripts/service/event_publisher.py       # 事件发布器
frontend/src/services/websocketClient.ts # WebSocket 客户端
frontend/src/hooks/useWebSocket.ts       # React hook
```

**修改文件**：
```
scripts/service/api.py                   # WebSocket 路由
scripts/service/trading_service.py       # 集成事件发布
scripts/main.py                          # 初始化 WebSocket manager
frontend/src/stores/tradingStore.ts      # 添加更新方法
frontend/src/pages/Trading.tsx           # 使用 useWebSocket hook
```

---

## 六、验证清单

- [ ] WebSocket 连接成功（前端控制台显示 "WebSocket connected"）
- [ ] 无 token 连接被拒绝
- [ ] 下单后前端收到 `order_matched` 事件
- [ ] 持仓自动更新
- [ ] 断网后自动重连
- [ ] 心跳正常工作

---

## 七、交接提示词

```
你现在接手 e:\stock-game 项目，P8 用户认证已完成（真实冒烟通过），现在进入 P9 WebSocket 实时推送阶段。

请阅读 docs/plans/2026-03-29-p9-websocket.md 了解详细任务：
1. P9-T1: 后端 WebSocket 路由（连接管理、认证、心跳）
2. P9-T2: 事件发布/订阅机制
3. P9-T3: 撮合引擎集成事件推送
4. P9-T4: 前端 WebSocket 连接管理（重连、心跳）
5. P9-T5: 前端事件处理与 store 更新

当前优先级：先完成 P9-T1（后端 WebSocket 路由）

硬约束：
- WebSocket 必须验证 JWT token
- 断线必须自动重连（最多 5 次）
- 每 30 秒发送心跳 ping

技术栈：
- 后端：FastAPI WebSocket + asyncio
- 前端：原生 WebSocket API + React hooks

验证方式：
- 下单后前端实时收到事件
- 持仓自动更新，无需手动刷新

建议从 P9-T1 开始，先实现 WebSocket 连接管理器。
```
