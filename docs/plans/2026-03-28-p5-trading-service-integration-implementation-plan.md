# P5 Trading Service Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将已完成的 P4 撮合引擎接入真实 PostgreSQL 与 API/时钟流程，形成可调用、可回放、可审计的交易服务闭环。

**Architecture:** 以 `scripts/engine` 为交易内核，新增 `scripts/service` 应用层负责 API 入参校验、状态读取、tick 推进与事件发布。数据持久化统一经 `PgState` 事务落库。时钟层按 `market_ticks` 驱动撮合并写入序列化事件，接口层仅作为薄适配。

**Tech Stack:** Python 3.13, psycopg2, unittest, PostgreSQL, (optional) FastAPI + Uvicorn for HTTP/WS adapter

---

### Task 1: 固化 DB 持久化引擎契约

**Files:**
- Modify: `scripts/engine/pg_state.py`
- Modify: `scripts/engine/orchestrator.py`
- Create: `tests/engine/test_pg_state_transaction.py`

**Step 1: Write the failing test**

```python
def test_pg_state_rolls_back_on_matching_error():
    # arrange fixture season/accounts/orders
    # force matcher exception
    # assert DB unchanged after exception
```

**Step 2: Run test to verify it fails**

Run: `set RUN_DB_INTEGRATION=1 && python -m unittest tests.engine.test_pg_state_transaction -v`
Expected: FAIL with partial-write or exception-path assertion mismatch.

**Step 3: Implement minimal transaction hardening**
- 在 `PgState.transaction()` 中补齐异常路径日志与状态恢复断言。
- 在 `EngineOrchestrator.process_tick()` 中统一异常包装并保留原异常链。

**Step 4: Run tests to verify pass**

Run: `set RUN_DB_INTEGRATION=1 && python -m unittest tests.engine.test_pg_state_transaction -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/engine/pg_state.py scripts/engine/orchestrator.py tests/engine/test_pg_state_transaction.py
git commit -m "test(engine): harden pg transaction rollback contract"
```

### Task 2: 构建交易应用服务层（非 HTTP）

**Files:**
- Create: `scripts/service/__init__.py`
- Create: `scripts/service/trading_service.py`
- Create: `tests/service/test_trading_service.py`

**Step 1: Write the failing test**

```python
def test_place_order_returns_reject_code_and_persists_order():
    svc = TradingService(...)
    result = svc.place_order(...)
    assert result["status"] in {"active", "rejected"}
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.service.test_trading_service -v`
Expected: FAIL with module/class not found.

**Step 3: Implement minimal service facade**
- 封装 `EngineOrchestrator.place_order/process_tick`。
- 增加 DTO 转换（数据库模型 -> API 响应字段）。
- 统一错误码映射（对齐 `docs/api/openapi.yaml`）。

**Step 4: Run tests to verify pass**

Run: `python -m unittest tests.service.test_trading_service -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/service/__init__.py scripts/service/trading_service.py tests/service/test_trading_service.py
git commit -m "feat(service): add trading service facade over engine"
```

### Task 3: 接入 API 层（REST 基础路径）

**Files:**
- Create: `scripts/service/api.py`
- Create: `tests/service/test_api_orders.py`
- Modify: `scripts/etl/requirements.txt`
- Modify: `docs/api/openapi.yaml` (only if field mapping drift is discovered)

**Step 1: Write the failing test**

```python
def test_post_order_returns_201_or_400_with_reject_code():
    resp = client.post("/v1/seasons/1/orders", json=payload)
    assert resp.status_code in (201, 400)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.service.test_api_orders -v`
Expected: FAIL with missing app/router.

**Step 3: Implement minimal HTTP adapter**
- 增加 `POST /v1/seasons/{seasonId}/orders`
- 增加 `GET /v1/seasons/{seasonId}/orders`
- 增加 `POST /v1/seasons/{seasonId}/orders/{orderId}/cancel`
- 返回结构与 `openapi.yaml` 对齐。

**Step 4: Run tests to verify pass**

Run: `python -m unittest tests.service.test_api_orders -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/service/api.py tests/service/test_api_orders.py scripts/etl/requirements.txt docs/api/openapi.yaml
git commit -m "feat(api): expose order endpoints backed by trading service"
```

### Task 4: 赛季时钟推进与撮合调度

**Files:**
- Create: `scripts/service/season_scheduler.py`
- Create: `tests/service/test_season_scheduler.py`

**Step 1: Write the failing test**

```python
def test_scheduler_processes_matching_ticks_only():
    processed = scheduler.run_once(season_id=1)
    assert processed["matching_ticks"] >= 1
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.service.test_season_scheduler -v`
Expected: FAIL with scheduler missing.

**Step 3: Implement minimal scheduler**
- 读取当前未处理 tick（按 `market_ticks` 时间序）
- 仅在 `is_matching_point=true` 调用 `TradingService.process_tick()`
- 写入处理序号（可先用内存/本地文件，后续升级为 DB 表）

**Step 4: Run tests to verify pass**

Run: `python -m unittest tests.service.test_season_scheduler -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/service/season_scheduler.py tests/service/test_season_scheduler.py
git commit -m "feat(service): add season tick scheduler for batch matching"
```

### Task 5: 事件发布与可回放审计

**Files:**
- Create: `scripts/service/events.py`
- Create: `tests/service/test_events.py`
- Create: `docs/reports/trade-replay-sample.json`

**Step 1: Write the failing test**

```python
def test_emit_trade_and_order_events_with_sequence():
    evt = bus.emit_trade(...)
    assert "sequence" in evt
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.service.test_events -v`
Expected: FAIL with events module missing.

**Step 3: Implement minimal event bus**
- 事件类型：`clock.tick`, `order.updated`, `trade.matched`, `leaderboard.updated`
- 每个事件附加 `sequence`, `serverTime`, `payload`
- 支持导出最近 N 条事件为 JSON（用于回放与审计）

**Step 4: Run tests to verify pass**

Run: `python -m unittest tests.service.test_events -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/service/events.py tests/service/test_events.py docs/reports/trade-replay-sample.json
git commit -m "feat(service): add sequenced event stream for replay audit"
```

### Task 6: 端到端回放闭环（下单 -> 撮合 -> 账本）

**Files:**
- Create: `tests/integration/test_trade_replay_db_flow.py`
- Modify: `tests/fixtures/minimal_season_fixture.json`
- Modify: `docs/plans/2026-03-28-progress.md`
- Modify: `scripts/etl/README.md`

**Step 1: Write the failing integration test**

```python
def test_db_flow_order_match_ledger_consistency():
    # place orders via service/api
    # run scheduler
    # assert orders/trades/accounts/positions/cash_ledger
```

**Step 2: Run test to verify it fails**

Run: `set RUN_DB_INTEGRATION=1 && python -m unittest tests.integration.test_trade_replay_db_flow -v`
Expected: FAIL due to missing service/scheduler/event integration.

**Step 3: Implement minimal glue code**
- 将任务 2-5 的模块串联成同一事务链路。
- 增加必要 fixture 字段（如账户/持仓初始状态）。

**Step 4: Run full test suite**

Run:
- `python -m unittest discover -s tests -p "test_*.py" -v`
- `set RUN_DB_INTEGRATION=1 && python -m unittest tests.integration.test_trade_replay_db_flow -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/integration/test_trade_replay_db_flow.py tests/fixtures/minimal_season_fixture.json docs/plans/2026-03-28-progress.md scripts/etl/README.md
git commit -m "test(integration): add db-backed replay flow from order to ledger"
```

---

## Exit Criteria

- API 层能受理下单并返回标准拒单码
- 匹配点推进可触发撮合并生成 `trades`
- 成交后账本与持仓更新一致，`cash_ledger` 可追踪
- 单测 + DB 集成测试稳定通过
- 进度文档和运行文档已更新
