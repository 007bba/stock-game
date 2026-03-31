# Stock Game v2 重构进度

- 日期：2026-03-31
- 来源文档：`docs/plans/stock-game.md`
- 当前目标：把产品从“赛季交易系统”收缩成“历史回放训练 + 下单理由 + 复盘”的最小闭环

## 今天已完成

- 前端路由从 `lobby / trading` 收缩为 `home / train / review`
- 首页已改成 v2 产品入口，支持选择训练场次
- 新增训练场次目录：`frontend/src/services/trainingCatalog.ts`
- 新增干净 demo season，用于隔离演示数据：
  - 2026-03-31 新建 `season_id=43`
  - `season_code=DEMO_CLEAN_20260331`
  - 从旧 replay season `39` 复制了股票池和行情回放数据
  - 没有复制 `accounts / orders / trades`，避免继续污染 `39`
- 前端 demo 默认入口已切到新的干净 season：
  - 训练预设默认 season 改为 `43`
  - 训练页 fallback season 改为 `43`
  - 本地 mock season 列表默认展示 `S43 干净 Demo 训练赛季`
  - 读取旧 localStorage 时会自动剔除内置 `S39` demo 项
- v2 后端独立骨架已落地：
  - 新增独立表设计：`market_sessions / market_session_positions / market_session_trades / market_session_trade_notes / market_session_results`
  - 新增独立 service：`scripts/service/market_session_service.py`
  - 新增 `/v2/market-sessions/*` API，不再继续复用旧 `season/accounts/orders` 模型承载 v2 训练场次
- 部署时自动 schema 应用已安排：
  - 新增 `scripts/apply_schema.py`
  - Docker 启动命令改成先执行 `python scripts/apply_schema.py`
  - Railway 从 GitHub 部署新镜像后会先补齐 `db/schema.sql` 再启动 API
- 训练状态已补齐：
  - 当前训练场次
  - 操作理由记录
  - 复盘摘要
- 训练页已改成 v2 语义：
  - 支持历史回放
  - 下单必须填写理由
  - 支持结束训练后跳转复盘页
- 复盘页已落地：
  - 总资产
  - 收益率
  - 胜率
  - 纪律评分
  - 操作与理由表

## 主要改动文件

- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/pages/Home.tsx`
- `frontend/src/pages/Trading.tsx`
- `frontend/src/pages/Review.tsx`
- `frontend/src/stores/tradingStore.ts`
- `frontend/src/components/OrderForm.tsx`
- `frontend/src/config/demoSeason.ts`
- `frontend/src/services/mockSeason.ts`
- `frontend/src/services/trainingCatalog.ts`
- `frontend/README.md`
- `scripts/service/market_session_service.py`
- `scripts/service/api.py`
- `scripts/main.py`
- `scripts/apply_schema.py`
- `db/schema.sql`
- `Dockerfile`
- `tests/service/test_market_session_api.py`
- `docs/plans/2026-03-31-v2-market-sessions-implementation-plan.md`

## 已验证

- 新 demo season 已创建完成：
  - `season_id=43`
  - `season_universe=24`
  - `market_ticks=1380`
  - `market_tick_quotes=31500`
  - `accounts=0`
  - `orders=0`
  - `trades=0`
- `python -m unittest tests.service.test_market_session_api tests.service.test_api_orders tests.service.test_tick_api -v` 通过
- `python -m py_compile scripts/service/market_session_service.py scripts/service/api.py scripts/main.py tests/service/test_market_session_api.py` 通过
- `cd frontend && npx tsc -p tsconfig.app.json --noEmit` 通过

## 未完成

- 后端仍然保留 `season` / 多人交易系统语义，但 v2 训练场次已经开始从独立 `/v2/market-sessions/*` 路径切出
- 目标数据库里还没有真正启用 v2 后端核心表：
  - `market_sessions`
  - `trades`
  - `trade_notes`
  - `session_results`
- 首页训练场次目前仍是前端静态目录，不是后端数据
- 训练结束后的评分逻辑目前是前端基础版规则
- v2 前端还没有真正接入新的 `/v2/market-sessions/*` API
- 还没有用线上 Railway 环境实际验证一次自动 schema 应用

## 明天建议优先做

1. push 到 GitHub，观察 Railway 新部署是否先执行 `apply_schema.py` 再成功启动
2. 在目标数据库确认 `market_sessions*` 表已出现
3. 让训练页从本地 session 切到 `/v2/market-sessions/*` API
4. 用真实 replay season 跑通一次：创建 session -> 拉 timeline -> 下单 -> finish -> result
5. 把复盘页改成读取后端结果，而不是只读前端本地摘要

## 备注

- `vite build` 在当前沙箱环境下因 `spawn EPERM` 失败，不是 TypeScript 或 ESLint 错误
- 如果部署环境显式配置了 `VITE_DEFAULT_SEASON_ID=39` 或 `AUTO_ADVANCE_SEASON_IDS=39`，需要同步切到 `43`
- 训练页里保留了“回放走后端、交易走本地模拟”的降级路径，方便先把训练闭环跑通
- 自动 schema 应用依赖 `db/schema.sql` 的幂等性；当前 DDL 已按 `IF NOT EXISTS` 风格维护，可重复执行
