# P5 本轮工作日志 —— PostgreSQL 持久化层实现

- 日期：2026-03-28
- 状态：**已完成**（P5 核心目标已达成，测试全部通过）

---

## 一、本轮完成内容

### 1.1 PgState 类实现 (`scripts/engine/pg_state.py`)

完全实现 PostgreSQL 后端状态类，替换 InMemoryState，支持事务落库：

- **`transaction()` 上下文管理器**：可重入事务（SAVEPOINT），最外层退出时 flush + commit
- **`_flush()` 批量 UPSERT**：将 orders / trades / accounts / positions / cash_ledger 批量写入 DB
- **`_flush_sequences()`**：用 `setval` 同步 PostgreSQL sequence，防止 nextval() 重号
- **`load_season_state()`**：从 DB 加载指定赛季的内存状态
- **全局 ID 查询**：`_max_id_for_table()` 和 `next_id` 查询均使用 **全局 MAX(id)**，而非分赛季查询

### 1.2 关键 Bug 修复

#### Bug 1：`effective_tick_id` 字段缺失
- **症状**：`Order` 缺少 `effective_tick_id` 字段，DB schema 有该列但 state.py 无对应属性
- **修复**：`state.py` 中 `Order` 类增加 `effective_tick_id: int | None = None`

#### Bug 2：`Position.last_buy_game_day` vs `last_settled_game_day` 列名不匹配
- **症状**：Python 字段名与 DB 列名不一致，导致持仓无法写入
- **修复**：`state.py` 中 `Position` 类字段从 `last_buy_game_day` 改为 `last_settled_game_day`，同步修改 `ledger.py`、`rules.py`

#### Bug 3：psycopg2 `conn.begin()` 不存在
- **症状**：`AttributeError: 'connection' object has no attribute 'begin'`
- **修复**：移除 `conn.begin()`，psycopg2 默认非 autocommit 模式

#### Bug 4：嵌套事务外层未 flush
- **症状**：`orch.place_order` 内部调用 `state.transaction()`，与外层 `process_tick` 嵌套
- **修复**：实现 `_tx_depth` 计数器 + SAVEPOINT，最外层退出时才 flush + commit

#### Bug 5：`ON CONFLICT (id)` 跨赛季冲突（根因 bug）
- **症状**：新赛季（season_id=19）下订单 commit 成功，但新连接查询结果为空
- **根因**：`load_season_state` 用 `WHERE season_id = X` 查 MAX(id)，新赛季 `next_order_id` 从 1 开始。
  `ON CONFLICT (id) DO UPDATE` 命中了 season 1 里 `id=1` 的旧订单，新订单数据被错误写入 season 1
- **修复**：
  ```python
  # 修复前（错误）：分赛季 MAX
  cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM orders WHERE season_id = %s", (season_id,))
  # 修复后（正确）：全局 MAX
  cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM orders")
  ```
  `_max_id_for_table()` 也改为全局查询

#### Bug 6：`sql.SQL().format()` 不支持 `%s`
- **症状**：`setval` 调用报错
- **修复**：改用普通字符串拼接

### 1.3 字段同步

| 文件 | 改动 |
|------|------|
| `scripts/engine/state.py` | `Position.last_buy_game_day` → `last_settled_game_day`；`Order` 增加 `effective_tick_id` |
| `scripts/engine/ledger.py` | 同步 `last_settled_game_day` |
| `scripts/engine/rules.py` | 同步 `last_settled_game_day` |
| `tests/engine/test_replay_e2e.py` | 同步字段名 |
| `db/schema.sql` | `orders` 表增加 `created_seq INT NOT NULL DEFAULT 0` |

### 1.4 测试结果

| 测试命令 | 结果 |
|---------|------|
| `python -m unittest tests.engine.test_pg_state_transaction -v` | **2/2 OK** |
| `python -m unittest tests.integration.test_trade_replay_db_flow -v` | **1/1 OK** |
| `python -m unittest discover -s tests -p "test_*.py" -v` | **24/24 OK（全部通过，无 skip）** |

> 上次报告 "19/19 OK, 2 skipped" 是因为当时 `DATABASE_URL` 环境变量未传入 shell。本次在有真实 Supabase DB 连接的情况下重跑，全部 24 个测试均通过，无 skip。

---

## 二、文件改动清单

### 新增文件
- `scripts/engine/pg_state.py` — PgState 实现
- `scripts/init_engine_db.py` — 种子数据初始化

### 修改文件
| 文件 | 关键改动 |
|------|---------|
| `scripts/engine/__init__.py` | 导出 PgState、apply_trade |
| `scripts/engine/orchestrator.py` | 接受 `InMemoryState \| PgState`，支持 season_id 参数 |
| `scripts/engine/state.py` | Position 字段名修正 + Order.effective_tick_id |
| `scripts/engine/ledger.py` | last_settled_game_day 同步 |
| `scripts/engine/rules.py` | last_settled_game_day 同步 |
| `db/schema.sql` | orders 增加 created_seq 列 |
| `tests/engine/test_replay_e2e.py` | 字段名同步 |

---

## 三、已验证的核心契约

1. **事务原子性**：异常时 DB 回滚，内存状态恢复 snapshot
2. **跨赛季 ID 唯一性**：orders.id / trades.id / cash_ledger.id 为全局主键，next_id 从全局 MAX() 计算
3. **可重入事务**：嵌套 `transaction()` 使用 SAVEPOINT，不泄漏外层事务
4. **Sequence 同步**：flush 后用 `setval` 同步 PostgreSQL sequence

---

## 四、下一步任务（给接手 AI 的建议）

### 高优先级

1. **修复 Supabase 连接问题**（如存在）
   - 验证 `DATABASE_URL` 格式正确（Supabase 提供的是 `postgres://` 而非 `postgresql://`）
   - 确认 PgBouncer 连接池配置（Supabase 使用 PgBouncer 代理）

2. **SeasonScheduler 完善**
   - 当前 `scripts/service/season_scheduler.py` 已实现基本框架
   - 需确认 `market_ticks` 表数据是否正确填充

3. **API 层路由对齐**
   - `scripts/service/api.py` 中的路由路径需与 `docs/api/openapi.yaml` 完全一致
   - 确认 `POST /v1/seasons/{seasonId}/orders` 的请求/响应格式

### 中优先级

4. **事件流可回放审计完善**
   - `scripts/service/events.py` 已有基本事件发布机制
   - 确认 `sequence` 连续性和 `serverTime` 时区正确性

5. **集成测试覆盖**
   - 现有 `tests/integration/test_trade_replay_db_flow.py` 通过
   - 可增加：取消订单场景、多股并发场景、跨日结算场景

### 低优先级（后续迭代）

6. **性能优化**
   - `_flush_orders()` 目前逐条 UPSERT，可改为批量 executemany
   - `load_season_state()` 可增加索引提示

7. **错误处理细化**
   - DB 连接断开重试逻辑
   - PgBouncer "connection already closed" 处理

---

## 五、关键参考文件

| 文件 | 用途 |
|------|------|
| `docs/plans/2026-03-28-p5-trading-service-integration-implementation-plan.md` | P5 完整 6-Task 计划 |
| `docs/plans/2026-03-28-progress.md` | 项目整体进度 |
| `docs/plans/2026-03-28-ai-handoff-p5.md` | 原始交接说明 |
| `db/schema.sql` | DDL 定义 |
| `docs/api/openapi.yaml` | API 契约 |

---

## 六、快速验证命令

```powershell
# 验证所有测试通过
python -m unittest discover -s tests -p "test_*.py" -v

# 验证 DB 集成测试（需 DATABASE_URL）
$env:RUN_DB_INTEGRATION = "1"
python -m unittest tests.integration.test_trade_replay_db_flow -v

# 验证 PgState 事务测试
python -m unittest tests.engine.test_pg_state_transaction -v
```

---

## 七、补充执行记录（AI Handoff P5 一键执行）

- 执行日期：2026-03-28
- 目标：按 `docs/plans/2026-03-28-ai-handoff-p5.md` 第 9 节顺序完成 1->4 验证并收口

### 7.1 本轮新增修复（先测后改）

- 新增失败测试：
  - `tests/service/test_api_orders.py`
    - `test_post_order_success_contains_contract_fields`
    - `test_cancel_order_returns_200_and_status_canceled`
    - `test_cancel_order_not_found_returns_contract_error`
  - `tests/service/test_trading_service.py`
    - 增加 `createdAt` 字段断言
- 首轮测试结果：`FAILED (2 failures)`，缺少 `createdAt`
- 实现修复：
  - `scripts/engine/state.py`：`Order` 增加 `created_at/updated_at`
  - `scripts/engine/orchestrator.py`：下单时写入 `created_at/updated_at`
  - `scripts/engine/matcher.py`：成交状态流转时刷新 `updated_at`
  - `scripts/service/trading_service.py`：DTO 输出 `createdAt/updatedAt`
  - `scripts/service/api.py`：路径参数对齐 `seasonId/orderId`；撤单时刷新 `updated_at`
  - `scripts/engine/pg_state.py`：订单 flush/load 持久化 `created_at/updated_at`
- 修复后契约测试结果：`OK (6 tests)`

### 7.2 一键执行命令与结果

1. `RUN_DB_INTEGRATION=1 python -m unittest tests.engine.test_pg_state_transaction -v`
   - 结果：`OK (2 tests, 1 skipped: psycopg2 is not installed)`
2. `RUN_DB_INTEGRATION=1 python -m unittest tests.integration.test_trade_replay_db_flow -v`
   - 结果：`OK (1 test, skipped: psycopg2 is not installed)`
3. `python -m unittest tests.service.test_season_scheduler -v`
   - 结果：`OK (1 test)`
4. `python -m unittest tests.service.test_api_orders -v`
   - 结果：`OK (5 tests)`
5. `python -m unittest tests.service.test_events -v`
   - 结果：`OK (2 tests)`
6. `python -m unittest discover -s tests -p "test_*.py" -v`
   - 结果：`OK (23 tests, 2 skipped)`

---

## 八、P5 收口补充（P6 交付准备）

- 日期：2026-03-28
- 目标：完成 P5 收口后，补齐环境注入、Scheduler 数据脚本、CI 触发策略

### 8.1 本地环境与脚本

1. 新增 `scripts/load_env.ps1`
   - 作用：在 PowerShell 会话内自动读取仓库根目录 `.env` 并注入环境变量
   - 约束：仅在变量未显式设置时注入，不覆盖当前 shell 已存在变量

2. 更新 `scripts/run_etl.ps1`
   - 变更：启动时自动调用 `scripts/load_env.ps1`
   - 结果：`DATABASE_URL`、`TUSHARE_TOKEN` 可从 `.env` 自动加载

3. 新增 `scripts/service/fill_market_ticks.py`
   - 作用：为 SeasonScheduler 依赖的 `market_ticks` 提供事务化补数脚本
   - 特性：支持 `--season-id/--start-date/--end-date/--exchange/--reset`，所有写入在单事务内完成

### 8.2 CI Workflow 最终状态（.github/workflows/etl-tests.yml）

1. `push` / `pull_request`
   - 触发：代码变更命中 `scripts/**`, `tests/**`, `db/**`, workflow 文件本身
   - 执行：`unit-tests`（默认不启用 DB 集成开关）

2. `workflow_dispatch`
   - 新增输入：`run_db_integration`（boolean，默认 true）
   - 执行：`integration-fixture`，注入
     - `DATABASE_URL: ${{ secrets.DATABASE_URL }}`
     - `RUN_DB_INTEGRATION: "1"`
   - 用例：
     - `tests.etl.test_db_fixture_integration`
     - `tests.engine.test_pg_state_transaction`
     - `tests.integration.test_trade_replay_db_flow`

3. `schedule`
   - 保持每日定时执行 DB 集成测试

4. Secrets 约束
   - 当 `secrets.DATABASE_URL` 为空时，`integration-fixture` 自动跳过，避免假阳性

### 8.3 本轮验证结论

- 工作流 YAML 语法检查：通过（无解析错误）
- 触发路径校对：通过（push 单测、workflow_dispatch DB 集成）
- 事务约束校对：通过（新增脚本使用 `engine.begin()` 单事务执行）

### 8.4 最终执行结果（本地连 Supabase）

1. `.\scripts\load_env.ps1`
   - 输出：`[load_env] loaded 2 env vars from E:\stock-game\.env`
   - 结论：PowerShell 会话内可自动获得 `DATABASE_URL`

2. `RUN_DB_INTEGRATION=1` 关键集成测试
   - `python -m unittest tests.etl.test_db_fixture_integration -v` → `OK (1 test)`
   - `python -m unittest tests.engine.test_pg_state_transaction -v` → `OK (2 tests)`
   - `python -m unittest tests.integration.test_trade_replay_db_flow -v` → `OK (1 test)`

3. 全量收口
   - `RUN_DB_INTEGRATION=1 python -m unittest discover -s tests -p "test_*.py" -v`
   - 结果：`OK (24 tests, 0 skipped)`

### 8.5 CI 对齐说明

- 为保证 GitHub Actions 与本地一致，workflow 的 `integration-fixture` 作业已补充 `pip install psycopg2-binary`
- `DATABASE_URL` 仅通过 `secrets.DATABASE_URL` 注入；代码中未硬编码 DB 凭据

