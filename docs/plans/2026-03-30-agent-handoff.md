# Agent 接手交接文档

## 项目背景

A 股仿真交易训练游戏，核心目的：训练用户「买龙头股抓涨停」的手感。
用户在历史数据回放中练习判断龙头股买入时机，形成真实市场的交易直觉。

## 当前进度

### 已完成

- **P7-P10**: 前端框架 + 认证 + WebSocket + 部署
- **P12**: tick 推进服务框架（SeasonScheduler + 手动推进 API + WebSocket 广播）
- **P14.5**: 多股票网格并列展示组件（MultiStockGrid + MiniKline）
- **赛季数据**: 赛季 ID=39（AI_DEC2025）已创建，24 只股票池已写入 `season_universe`
- **部署**: 后端 Railway + 前端 Cloudflare Pages

### 未完成（硬阻塞）

- **market_ticks 和 market_tick_quotes 为空** — ETL 的 `sync_minute_bars` 和 `compress_season` 未成功运行
  - 原因：Tushare 免费账户分钟线接口受限（每天只能访问2次），降级到日线合成
  - ETL 的 `compress` 步骤依赖 `raw_minute_bars` 有数据，但看起来上次 ETL 在 `bars` 步骤就异常退出了
  - 需要重跑 ETL 的 `bars` + `compress` 阶段

## 关键文件索引

| 文件 | 作用 |
|------|------|
| `scripts/etl/tushare_pipeline.py` | ETL 管线：日历同步 + 分钟线下载 + 停复牌 + 压缩 |
| `scripts/etl/select_ai_leaders.py` | AI 龙头股筛选脚本 |
| `scripts/main.py` | FastAPI 入口，已集成 scheduler + replay_data + auto_advance |
| `scripts/service/season_scheduler.py` | tick 推进核心逻辑 + DB tick/quote loader |
| `scripts/service/replay_data.py` | 回放数据查询服务（get_tick / list_tick_quotes） |
| `scripts/service/api.py` | REST API，含 `GET /ticks/current` 和 `POST /ticks/advance` |
| `frontend/src/components/MultiStockGrid.tsx` | 多股票网格组件（2x2/3x3/4x4） |
| `frontend/src/components/MiniKline.tsx` | 迷你 K 线面积图 |
| `frontend/src/pages/Trading.tsx` | 交易页，已接入网格 + tick 推进 |
| `frontend/src/stores/tradingStore.ts` | 交易状态管理（tick 元信息 + quotes 缓存） |
| `frontend/src/hooks/useTradingWebSocket.ts` | WebSocket，已处理 tick_advance / tick_update |
| `docs/plans/2026-03-30-next-phase-training.md` | 完整功能规划（P12-P16） |
| `docs/plans/2026-03-27-stock-game-design.md` | 产品设计文档 |

## 技术栈

- 后端：Python 3.12 + FastAPI + SQLAlchemy
- 前端：React + TypeScript + Vite + Ant Design + Lightweight Charts
- 数据库：Supabase PostgreSQL
- 认证：Supabase Auth JWKS
- 数据源：Tushare（分钟线/日线）

## 环境变量

```
DATABASE_URL=postgresql://postgres:nyWGaq191SUOxMvu@db.oszikuwftdlsnjkheczh.supabase.co:5432/postgres
TUSHARE_TOKEN=cfac8ec330b097ef3a83374e626975b3407db2c853d60b4271766a59
SUPABASE_URL=https://oszikuwftdlsnjkheczh.supabase.co
SUPABASE_JWT_SECRET=mLNQj4f3YE/YEUD3Z2bsKRj4/M+6jPRW0RNjOiaSbnHM50UFUE6lOAMTWpvBejXfQDz+NoUxT+qatKqPX1Jjxg==
SUPABASE_JWT_AUDIENCE=authenticated
```

## 下一步任务（按优先级）

### 任务 0（P0，10分钟）：环境预检（先做）

当前仓库只有一个 Python 依赖清单：`scripts/etl/requirements.txt`。
`scripts/main.py` 会直接 `from dotenv import load_dotenv`，如果环境没装 `python-dotenv` 会在启动阶段直接报错。

```powershell
cd e:\stock-game

# 安装本项目 Python 依赖（包含 python-dotenv）
pip install -r scripts/etl/requirements.txt

# 加载 .env 到当前 PowerShell 会话
.\scripts\load_env.ps1

# 快速确认关键变量
Write-Host "DATABASE_URL set:" ([string]::IsNullOrWhiteSpace($env:DATABASE_URL) -eq $false)
Write-Host "TUSHARE_TOKEN set:" ([string]::IsNullOrWhiteSpace($env:TUSHARE_TOKEN) -eq $false)
```

若上一步返回 `False`，优先修正 `.env` 或当前 shell 变量，再进入 ETL。

### 任务 1（P0，阻塞一切）：补齐压缩回放数据

上次 ETL 运行 `sync_minute_bars` 时，Tushare 免费账户受限，降级到日线合成伪分钟线。但 `compress_season` 可能没有成功运行。

**操作步骤**：
1. 验证 `raw_minute_bars` 表是否有赛季 39 的数据
2. 如果有数据：直接运行 `compress` 阶段
3. 如果没数据：运行 `bars` 阶段（会降级到日线合成）+ `compress` 阶段

```powershell
cd e:\stock-game
$env:TUSHARE_TOKEN='cfac8ec330b097ef3a83374e626975b3407db2c853d60b4271766a59'
$env:DATABASE_URL='postgresql://postgres:nyWGaq191SUOxMvu@db.oszikuwftdlsnjkheczh.supabase.co:5432/postgres'

# 先只跑 bars（如果 raw_minute_bars 为空）
python scripts/etl/tushare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-31 --mode bars

# 再跑 compress
python scripts/etl/tushare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-31 --mode compress

# 验证
python scripts/etl/tushare_pipeline.py --season-id 39 --mode validate
```

**验证标准**：
- `market_ticks` 表应有 60 × N 条记录（N = 2025年12月交易日数，约 22 天 → ~1320 条）
- `market_tick_quotes` 表应有 60 × N × 24 条记录（~31,680 条）

### 任务 2（P0）：端到端联调验证

数据就绪后，本地启动后端验证：

```powershell
cd e:\stock-game
$env:DATABASE_URL='postgresql://postgres:nyWGaq191SUOxMvu@db.oszikuwftdlsnjkheczh.supabase.co:5432/postgres'
$env:AUTO_ADVANCE_SEASON_IDS='39'
$env:TICK_ADVANCE_INTERVAL_SECONDS='3'
python scripts/main.py
```

验证点：
1. `GET http://localhost:8000/v1/seasons/39/ticks/current` 返回 tick + quotes
2. `POST http://localhost:8000/v1/seasons/39/ticks/advance` 推进成功
3. WebSocket `/ws/39` 收到 `tick_advance` 事件
4. 前端 `http://localhost:5173` 网格能显示股票数据

最小冒烟（后端/回放核心）：

```powershell
cd e:\stock-game
python -m unittest tests.engine.test_replay_e2e -v
python -m unittest tests.integration.test_trade_replay_db_flow -v
```

说明：第二条是 DB 集成用例，需确保当前 shell 里 `DATABASE_URL` 已正确加载。

### 任务 3（P1）：K 线回放完善

当前 KlineChart 已支持渲染后端 candles，但需要：
- tick 推进时，将 quote 数据追加为新的 candle（而非只更新 store）
- 每个 matching point 确认一个 5 分钟 candle
- 非匹配点实时更新当前 candle 的 close

### 任务 4（P1）：集合竞价训练（P13）

- 竞价阶段（minute 1-3, 58-60）禁止撤单
- 开盘/收盘撮合：最大成交量原则计算开盘价
- 竞价 imbalance 提示（已有 `auction_hint_level` 字段）

### 任务 5（P2）：排行榜

- 收益率排名
- 最大回撤指标
- 赛季维度排行

## 用户核心需求

> 「我的目的是设计一个能训练我买龙头股抓涨停的感觉，能否展示多个股票并列，同时看到他们的走势，便于判断」

重点：多股票并列对比 + 时间压缩回放 + 集合竞价判断。

## 部署信息

- 后端：https://stock-game-production-99e8.up.railway.app
- 前端：https://stock-game-4cp.pages.dev
- Railway 需要的环境变量：`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWT_AUDIENCE`, `SUPABASE_USE_JWKS=true`, `PYTHONPATH=/app`, `AUTO_ADVANCE_SEASON_IDS=39`, `TICK_ADVANCE_INTERVAL_SECONDS=5`
