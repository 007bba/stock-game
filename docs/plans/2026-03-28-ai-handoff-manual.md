# Stock Game AI 交接说明书（含 P4）

- 文档日期：2026-03-28
- 适用对象：任意可执行代码改动的 AI 编码助手
- 目标：让新 AI 在无上下文情况下也能继续完成剩余任务

## 1. 项目当前状态（必须先读）

已完成：
- 数据基础：`db/schema.sql`
- API 契约：`docs/api/openapi.yaml`
- ETL 管道：`scripts/etl/tushare_pipeline.py`
- 压缩校验：`scripts/etl/validate_compression.py`
- 自动化测试：`tests/etl`（单测 + 可选 DB fixture 测试）
- CI 工作流：`.github/workflows/etl-tests.yml`

已验证：
- `python scripts/etl/tushare_pipeline.py --mode all --season-id 1 --start-date 2026-01-06 --end-date 2026-01-07` 成功
- `python -m unittest discover -s tests -p "test_*.py" -v` 通过
- `RUN_DB_INTEGRATION=1` 的 fixture 集成测试可通过

剩余核心任务（P4）：
1. 启动撮合与规则引擎实现（服务端权威）
2. 增加端到端回放用例（下单 -> 撮合 -> 账本）

## 2. 代码与规则基准

必须遵守的业务规则（来自设计文档）：
- T+1（当日买入不可卖出）
- 100 股一手
- 涨跌停限制
- 停牌不可成交
- 每 5 分钟统一撮合
- 集合竞价与连续竞价阶段差异（使用 `market_ticks` 的 `phase/matching_mode`）

权威参考文件：
- 规则说明：`docs/plans/2026-03-27-stock-game-design.md`
- 数据结构：`db/schema.sql`
- API 契约：`docs/api/openapi.yaml`
- 进度：`docs/plans/2026-03-28-progress.md`

## 3. 环境与运行约定

环境变量：
- `DATABASE_URL` 必填
- `TUSHARE_TOKEN` ETL 相关任务需要
- `RUN_DB_INTEGRATION=1` 才执行 DB fixture 集成测试

常用命令：
- 单测：`python -m unittest discover -s tests -p "test_*.py" -v`
- fixture 测试：`python -m unittest tests.etl.test_db_fixture_integration -v`
- ETL 全链路：`python scripts/etl/tushare_pipeline.py --mode all --season-id 1 --start-date 2026-01-06 --end-date 2026-01-07`

## 4. P4 任务拆解（给 AI 的执行步骤）

### P4-1：实现撮合与规则引擎（服务端权威）

建议新增目录（如无冲突可直接采用）：
- `src/engine/`（或 `scripts/engine/`，二选一并保持一致）

建议最小模块：
1. `rules.py`
- 校验下单合法性：
  - 手数（`quantity % 100 == 0`）
  - 涨跌停价格边界（用 `market_tick_quotes.upper/lower_limit_price`）
  - 停牌校验（`is_halted`）
  - 卖出可用数量校验（`positions.qty_sellable`）
  - 资金可用校验（`accounts.available_cash` + 费用）
  - T+1 校验
- 输出统一拒单码（对齐 OpenAPI 的 `RejectCode`）

2. `matcher.py`
- 在匹配点（`market_ticks.is_matching_point=true`）执行批量撮合
- 先实现 MVP 版本：
  - 买单按价格降序/时间升序
  - 卖单按价格升序/时间升序
  - 成交价先采用 tick 的 `ref_price`（后续可升级“最大成交量价”）
  - 更新：`orders.remaining_qty/status`, `trades`

3. `ledger.py`
- 处理成交后的账务变更：
  - `accounts.available_cash/frozen_cash/realized_pnl`
  - `positions.qty_total/qty_sellable/avg_cost`
  - `cash_ledger` 写流水（含 fee/tax）

4. `orchestrator.py`
- 按 tick 驱动：
  - 非匹配点：仅受理订单
  - 匹配点：规则校验 -> 撮合 -> 账本更新 -> 状态落库

落库要求：
- 全部状态变更必须在事务内完成
- 任何失败要回滚并记录可定位错误

### P4-2：增加端到端回放用例（下单 -> 撮合 -> 账本）

新增测试文件建议：
- `tests/engine/test_replay_e2e.py`

至少覆盖 5 类场景：
1. 正常买入成交（整手，价格合法）
2. 非整手拒单（`LOT_SIZE_INVALID`）
3. 涨跌停越界拒单（`LIMIT_PRICE_OUT_OF_BAND`）
4. T+1 卖出拒单（`SELL_T1_BLOCKED`）
5. 停牌拒单（`STOCK_HALTED`）

测试断言最少包含：
- `orders.status/reject_code`
- `trades` 行数与数量
- `accounts` 与 `positions` 关键字段变化
- `cash_ledger` 记录完整

## 5. 验收标准（AI 完成后必须满足）

功能验收：
- 能在本地执行一次“模拟下单 + tick 撮合 + 账本变更”完整流程
- 拒单码与 OpenAPI 定义一致
- 写库事务一致性正确，无半成功状态

测试验收：
- `python -m unittest discover -s tests -p "test_*.py" -v` 全通过
- 新增 E2E 用例可重复通过
- 如依赖数据库，默认用开关控制，避免阻塞无 DB 场景

文档验收：
- 更新 `docs/plans/2026-03-28-progress.md`
- 在 README 或新文档写清新增模块运行方式

## 6. 不要踩的坑

- 不要把明文 `DATABASE_URL/TUSHARE_TOKEN` 写入仓库
- 不要破坏现有 ETL 能力（`all/validate/report-out`）
- 不要修改已稳定测试的语义（除非同步更新测试与文档）
- 不要引入无法安装的重依赖，优先使用标准库 + 现有依赖

## 7. 推荐给其他 AI 的提示词模板（可直接复制）

```text
你现在接手 e:\stock-game 项目。请严格按 docs/plans/2026-03-28-ai-handoff-manual.md 执行。
目标：完成 P4
1) 实现服务端权威规则引擎与撮合内核（含账本变更）
2) 新增端到端回放测试（下单->撮合->账本）

硬约束：
- 规则必须包含 T+1、整手、涨跌停、停牌、资金/持仓校验
- 拒单码对齐 docs/api/openapi.yaml
- 所有落库变更走事务
- 不写入任何明文密钥

完成后输出：
- 变更文件清单
- 运行的测试命令与结果
- 仍存风险与下一步建议
```
