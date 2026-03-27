# Stock Game MVP Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立可直接开工的后端基础规范，包含数据库结构、核心 API 契约、Tushare 数据导入与压缩机制。

**Architecture:** 使用 PostgreSQL 作为权威账本与行情回放存储，统一通过 REST + WebSocket 提供状态与交易事件。数据侧采用 Tushare 离线 ETL，将分钟级真实数据压缩为游戏时钟可回放的 tick。撮合与规则由服务端权威执行，客户端仅展示与发单。

**Tech Stack:** PostgreSQL 15+, OpenAPI 3.1, WebSocket, Python ETL（Tushare SDK + pandas）

---

### Task 1: 产出数据库 DDL（交易规则可承载）

**Files:**
- Create: `db/schema.sql`

**Step 1: 定义基础实体与枚举**
- `users`、`seasons`、`season_universe`、`market_ticks`
- 枚举：订单方向、订单状态、时段类型

**Step 2: 定义交易账本实体**
- `accounts`、`positions`、`orders`、`trades`、`cash_ledger`
- 增加主外键、唯一键、检查约束（如 100 股一手）

**Step 3: 定义行情与数据导入实体**
- `trading_calendar`、`raw_minute_bars`、`corp_actions`、`etl_jobs`
- 增加时间与代码复合索引

**Step 4: 补充关键索引与注释**
- 针对下单查询、成交回放、榜单读取建立索引

**Step 5: 自检语义一致性**
- 核对字段是否覆盖：T+1、停牌、涨跌停、竞价阶段

### Task 2: 产出 API 契约（REST + WebSocket）

**Files:**
- Create: `docs/api/openapi.yaml`

**Step 1: 定义核心 REST 路由**
- 赛季、行情、下单、撤单、持仓、账本、榜单

**Step 2: 定义请求/响应模型**
- 下单请求（限价单）
- 订单状态查询
- 资产与仓位快照

**Step 3: 定义错误码与规则错误映射**
- 涨跌停越界、非整手、T+1 卖出不足、停牌不可交易

**Step 4: 定义 WebSocket 事件模型**
- tick 推进、撮合结果、订单状态变更、排行榜刷新

**Step 5: 自检契约与 DDL 对齐**
- 字段命名、状态枚举、ID 与时间戳一致

### Task 3: 产出 Tushare ETL 与压缩规范

**Files:**
- Create: `docs/specs/tushare-etl-compression.md`

**Step 1: 定义数据来源与字段映射**
- Tushare 接口到 `raw_minute_bars` / `corp_actions` 映射

**Step 2: 定义日内压缩映射**
- 3+26+2+26+3 分钟结构
- 5 分钟统一撮合与竞价窗口处理

**Step 3: 定义压缩输出结构**
- `market_ticks` 的 ref_price、vwap、volume_factor、limit_flag

**Step 4: 定义数据质量校验**
- 时间连续性、涨跌停边界、停牌窗口校验

**Step 5: 定义运行流程与失败恢复**
- `etl_jobs` 状态机、幂等重跑、日志落库

### Task 4: 交付审阅与下一步启动包

**Files:**
- Modify: `docs/plans/2026-03-27-stock-game-design.md`

**Step 1: 回填已完成交付链接**
- 将 DDL/API/ETL 三份文档挂回设计文档

**Step 2: 输出首期开发顺序建议**
- 先规则引擎，再撮合，再联机，再前端

**Step 3: 标注剩余唯一待定项**
- 仅保留未来对外运营时的授权事项
