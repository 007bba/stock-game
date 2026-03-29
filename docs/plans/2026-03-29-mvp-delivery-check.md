# Stock Game 明日任务安排（P6 收口 + MVP 交付检查）

- 文档日期：2026-03-28（面向 2026-03-29 执行）
- 当前项目状态：**P5 已完成（24/24 测试通过），P6 收尾已完成，本地验证全部通过，等待 GitHub Actions 云端验证**
- 目标：完成 MVP 交付前最后检查，确认 CI/CD 链路真实可用

---

## 一、目标

1. **GitHub Actions 云端验证**：推送当前分支，验证 `push` 触发单测 job 执行成功
2. **workflow_dispatch 手动触发 DB 集成测试**：在 GitHub Actions 页面手动触发 `integration-fixture` job，确认 Supabase 连通
3. **交付文档完整性复核**：确认 runbook、API 文档、测试报告三者一致
4. **种子数据可运行性验证**：执行 `python scripts/init_engine_db.py` 确认赛季/账户/行情数据可正常初始化

---

## 二、硬约束

- `DATABASE_URL` **不得**出现在任何代码文件（`.py`）中，仅允许通过环境变量或 GitHub Secrets 注入
- 所有 DB 写入必须为单事务，不允许半成功落库
- 拒单码必须与 `docs/api/openapi.yaml` 一致，API 测试不得因契约变更失败
- ETL 主命令 `python scripts/etl/tushare_pipeline.py --mode all --season-id 1 ...` 不得被破坏
- `.env` 文件已加入 `.gitignore`，不得提交至版本库
- GitHub Secrets 中的 `DATABASE_URL` 必须在仓库 Settings → Secrets 中手动添加（本次无法自动完成，依赖人工操作）

---

## 三、执行任务清单

### Task 1：推送代码并触发 GitHub Actions 单测（云端）

**前置条件：** 所有本地测试已通过（24/24 OK）

**操作步骤：**

```bash
# 1. 检查 git status
git status

# 2. 添加所有改动
git add -A

# 3. 提交（标注 P5 + P6 收口）
git commit -m "feat: P5+P6 complete - PgState persistence, CI/CD, market_ticks filler, runbook

- PgState with SAVEPOINT transactions, global ID fix
- fill_market_ticks.py for season_scheduler data prep
- load_env.ps1 for PowerShell .env auto-injection
- CI: push=unit-tests, workflow_dispatch=DB integration
- 24/24 tests pass locally (Supabase)"

# 4. 推送到 origin/main
git push origin main
```

**验证方式：**
- 打开 GitHub 仓库 → Actions 标签页
- 确认 `push` 触发的 workflow 运行成功（绿色勾）
- 确认 `unit-tests` job 通过（无需 DB）

---

### Task 2：手动触发 workflow_dispatch 验证 DB 集成（云端）

**前置条件：** Task 1 完成，且 `secrets.DATABASE_URL` 已在仓库中配置

**操作步骤：**

1. 在 GitHub 仓库页面 → Actions → 选择 "ETL Tests" workflow
2. 点击 "Run workflow" → 确认 `run_db_integration: true`
3. 等待 `integration-fixture` job 执行

**验证方式：**
- `integration-fixture` job 状态为绿色通过
- 日志中包含：
  - `pip install psycopg2-binary` 成功
  - `tests.etl.test_db_fixture_integration` → `OK`
  - `tests.engine.test_pg_state_transaction` → `OK`
  - `tests.integration.test_trade_replay_db_flow` → `OK`

**如 `secrets.DATABASE_URL` 未配置：**
- 跳过 Task 2，仅确认 Task 1 单测通过
- 在文档中标注 "DB 集成测试需人工配置 GitHub Secrets DATABASE_URL"

---

### Task 3：种子数据可运行性验证（本地）

**操作步骤：**

```powershell
# 加载环境变量
.\scripts\load_env.ps1

# 初始化引擎数据库（种子数据）
python scripts/init_engine_db.py
```

**验证方式：**
- 脚本执行成功，无异常退出
- DB 中 `seasons`、`accounts`、`season_universe` 表有数据

---

### Task 4：market_ticks 填充脚本验证（本地）

**操作步骤：**

```powershell
.\scripts\load_env.ps1

# 填充 season_id=1 的 market_ticks（默认 10 个 game days，每天 60 ticks）
python scripts/service/fill_market_ticks.py --season-id 1 --reset
```

**验证方式：**
- `market_ticks` 表中 season_id=1 的记录数 = 10 days × 60 ticks = 600 条
- 每条 tick 的 `is_matching_point` 为 true 的数量符合预期（每分钟 1 个 matching point）

---

### Task 5：交付文档完整性复核

**检查项：**

| 文档 | 路径 | 检查点 |
|------|------|--------|
| 项目进度 | `docs/plans/2026-03-28-progress.md` | P5 行已标记 100%，无遗漏任务 |
| P5 会话日志 | `docs/plans/2026-03-28-p5-session-log.md` | 包含全部 bug 修复记录和最终测试结果 |
| AI 交接说明 | `docs/plans/2026-03-28-ai-handoff-p5.md` | 执行命令、约束条件、文件清单完整 |
| API 契约 | `docs/api/openapi.yaml` | 与 `scripts/service/api.py` 路由/字段一致 |
| DDL | `db/schema.sql` | 与 `scripts/engine/state.py` 模型字段一致 |
| ETL 使用说明 | `scripts/etl/README.md` | 命令示例与实际参数一致 |

---

### Task 6：最终全量测试收口（本地）

**操作步骤：**

```powershell
.\scripts\load_env.ps1
$env:RUN_DB_INTEGRATION = "1"

# 全量测试
python -m unittest discover -s tests -p "test_*.py" -v
```

**验证方式：**
- 输出：`OK (24 tests, 0 skipped)`
- 无红色 FAILED 或 ERROR

---

## 四、完成后输出

### 4.1 交付清单（checklist）

- [ ] Task 1：`push` 触发 GitHub Actions `unit-tests` 绿色通过
- [ ] Task 2：`workflow_dispatch` 触发 `integration-fixture` 绿色通过（若 Secrets 已配置）
- [ ] Task 3：`init_engine_db.py` 执行成功，DB 有种子数据
- [ ] Task 4：`fill_market_ticks.py` 写入 600 条 tick 记录
- [ ] Task 5：6 份文档复核一致
- [ ] Task 6：24/24 测试全部通过，0 skipped

### 4.2 最终输出文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 明日任务本文档 | `docs/plans/2026-03-29-mvp-delivery-check.md` | 本文档，已在本轮生成 |
| P5 会话日志（终态） | `docs/plans/2026-03-28-p5-session-log.md` | 包含 P6 收口补充章节 |
| 项目进度（终态） | `docs/plans/2026-03-28-progress.md` | P5 已标记 100% |

---

## 五、快速验证命令（明日执行）

```powershell
# 0. 前置：加载环境变量
.\scripts\load_env.ps1

# 1. 单测 + DB 集成全量
$env:RUN_DB_INTEGRATION = "1"
python -m unittest discover -s tests -p "test_*.py" -v
# 期望：OK (24 tests, 0 skipped)

# 2. 种子数据初始化
python scripts/init_engine_db.py
# 期望：无异常

# 3. market_ticks 填充
python scripts/service/fill_market_ticks.py --season-id 1 --reset
# 期望：写入 600 条 tick

# 4. push 触发 CI 后在 GitHub Actions 页面验证
# https://github.com/<owner>/stock-game/actions
```

---

## 六、已知限制

1. **GitHub Secrets DATABASE_URL**：需仓库管理员在 GitHub 仓库 Settings → Secrets → Actions 中手动添加 `DATABASE_URL`，AI 无法自动配置云端 Secrets
2. **Supabase 连接池**：PgBouncer 在某些长事务场景下可能报 "connection already closed"，如遇此情况需在 `pg_state.py` 增加重试逻辑
3. **tushare API 限流**：ETL 管道测试中 `test_call_tushare_with_retry` 存在概率性重试（正常行为），不影响交付

---

## 七、交接提示词（给下一位 AI）

```
你现在接手 e:\stock-game 项目，P5+P6 收口已完成。请严格按 docs/plans/2026-03-29-mvp-delivery-check.md 执行明日任务：
1. 推送代码触发 GitHub Actions 单测
2. 手动触发 workflow_dispatch 验证 DB 集成（如 Secrets 已配置）
3. 执行本地种子数据 + market_ticks 填充验证
4. 复核 6 份交付文档一致性
5. 执行最终全量测试（24/24 OK, 0 skipped）

硬约束：
- DATABASE_URL 禁止硬编码，仅从环境变量或 GitHub Secrets 读取
- 所有 DB 写入必须为单事务
- 拒单码与 openapi.yaml 一致
- ETL 主命令不得被破坏
```
