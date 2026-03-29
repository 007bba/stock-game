# Stock Game AI 交接说明书（P5）

- 文档日期：2026-03-28
- 适用对象：任意可执行代码改动的 AI 编码助手
- 目标：在 P4 已完成基础上，推进 P5（交易服务集成）

## 1. 当前状态

已完成：
- P4 撮合/规则引擎：`scripts/engine/*`
- P4 回放测试：`tests/engine/test_replay_e2e.py`
- ETL 与压缩回放链路：`scripts/etl/*`
- 单测与 fixture 测试：`tests/etl/*`, `tests/fixtures/*`

主参考：
- 进度：`docs/plans/2026-03-28-progress.md`
- 设计：`docs/plans/2026-03-27-stock-game-design.md`
- P5 计划：`docs/plans/2026-03-28-p5-trading-service-integration-implementation-plan.md`

## 2. P5 目标

1. 对接真实 DB 持久化事务实现（引擎 -> PostgreSQL）
2. 接入 API 层与赛季时钟推进（形成可调用服务）
3. 完成 DB 端到端回放测试（下单 -> 撮合 -> 账本）

补充状态：
- P5 核心链路已完成并在进度文档标记
- 本轮后续工作以“高/中优先级收口验证”为主

## 3. 强约束

- 拒单码与 `docs/api/openapi.yaml` 一致
- 事务一致性：不得出现半成功落库
- 不写入明文密钥
- 不破坏现有 ETL 与测试命令

## 4. 执行顺序

请严格按下列顺序执行：
1. `docs/plans/2026-03-28-p5-trading-service-integration-implementation-plan.md` Task 1-6
2. 每个 Task 完成后先跑对应测试再提交
3. 全部完成后更新 `docs/plans/2026-03-28-progress.md`

## 5. 建议执行命令

- 单测：`python -m unittest discover -s tests -p "test_*.py" -v`
- DB fixture：`set RUN_DB_INTEGRATION=1 && python -m unittest tests.etl.test_db_fixture_integration -v`
- 全链路 ETL：`python scripts/etl/tushare_pipeline.py --mode all --season-id 1 --start-date 2026-01-06 --end-date 2026-01-07`

## 6. 给接手 AI 的下一步任务（优先级）

高优先级：验证 Supabase 连接（DATABASE_URL 格式）
- 目标：确认数据库连接串可被当前 Python 运行环境识别并可成功建连
- 建议检查：
	- 协议前缀正确（如 `postgresql://`）
	- 主机、端口、库名、用户名齐全
	- 密码中若含特殊字符需 URL 编码
	- SSL 参数满足 Supabase 连接要求
- 验收命令：
	- `set RUN_DB_INTEGRATION=1 && python -m unittest tests.engine.test_pg_state_transaction -v`
	- `set RUN_DB_INTEGRATION=1 && python -m unittest tests.integration.test_trade_replay_db_flow -v`

高优先级：SeasonScheduler 完善
- 目标：确认 `market_ticks` 数据填充完整、推进顺序正确、检查点持久化无断点回退
- 验收命令：
	- `python -m unittest tests.service.test_season_scheduler -v`
	- 若接 DB，补跑 `tests.integration.test_trade_replay_db_flow`

中优先级：API 路由与 openapi.yaml 对齐
- 目标：`POST/GET/cancel` 路由响应字段与契约一致（字段名、状态码、reject code）
- 验收命令：
	- `python -m unittest tests.service.test_api_orders -v`
	- 对照 `docs/api/openapi.yaml` 做字段核对（必要时补充 API 测试断言）

中优先级：事件流 sequence 连续性验证
- 目标：确认事件 envelope 中 `sequence` 严格递增、导出回放顺序一致
- 验收命令：
	- `python -m unittest tests.service.test_events -v`
	- 抽查 `docs/reports/trade-replay-sample.json`

## 7. 完成定义（收口）

- 所有 service 单测通过：`tests.service.*`
- DB 环境可用时，两条 DB 集成链路测试通过：
	- `tests.engine.test_pg_state_transaction`
	- `tests.integration.test_trade_replay_db_flow`
- 文档同步：
	- 更新 `docs/plans/2026-03-28-progress.md`
	- 记录本轮执行日志（建议新增同日 session log 文件）

## 8. 可直接复制给其他 AI 的提示词

```text
你现在接手 e:\stock-game 项目，P4 已完成。请严格按 docs/plans/2026-03-28-ai-handoff-p5.md 和 docs/plans/2026-03-28-p5-trading-service-integration-implementation-plan.md 执行 P5。
要求：
- 每个 Task 先写测试再实现
- 每个 Task 都要给出运行命令和结果
- 拒单码必须对齐 docs/api/openapi.yaml
- 所有 DB 写入必须在事务内
- 完成后更新 docs/plans/2026-03-28-progress.md
```

## 9. 一键执行清单（接手 AI）

执行顺序：严格从 1 到 4，不要跳步。

1. 验证 Supabase 连接
- 命令：
	- `set RUN_DB_INTEGRATION=1 && python -m unittest tests.engine.test_pg_state_transaction -v`
	- `set RUN_DB_INTEGRATION=1 && python -m unittest tests.integration.test_trade_replay_db_flow -v`
- 预期：两条命令在有 DB 环境时通过；若环境不完整可见明确 skip 信息。
- 失败排查：
	- 检查 `DATABASE_URL` 是否完整且可连通
	- 检查是否已安装 `psycopg2` 或兼容驱动
	- 检查 Supabase SSL 参数与防火墙访问

2. SeasonScheduler 完善验证
- 命令：`python -m unittest tests.service.test_season_scheduler -v`
- 预期：通过，且断言只在撮合点触发处理。
- 失败排查：
	- 检查 `scripts/service/season_scheduler.py` 的 tick 排序与 checkpoint 行为
	- 检查 quote loader 返回结构是否与 `Quote` 对齐

3. API 与契约对齐验证
- 命令：`python -m unittest tests.service.test_api_orders -v`
- 预期：通过，POST/GET/cancel 的状态码与返回字段符合契约。
- 失败排查：
	- 对照 `docs/api/openapi.yaml` 检查字段命名（camelCase）
	- 确认 reject code 与枚举一致

4. 事件流 sequence 连续性验证
- 命令：`python -m unittest tests.service.test_events -v`
- 预期：通过，事件 sequence 单调递增且导出顺序正确。
- 失败排查：
	- 检查 `scripts/service/events.py` 的 sequence 自增与 latest(limit) 实现
	- 抽查 `docs/reports/trade-replay-sample.json`

最终收口命令：
- `python -m unittest discover -s tests -p "test_*.py" -v`

收口通过标准：
- service 单测全部通过
- DB 环境可用时 DB 集成链路通过
- 进度文档与当日执行日志已更新
