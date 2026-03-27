# Tushare ETL 与 1 小时压缩规范（MVP）

- 日期：2026-03-27
- 场景：仅内部训练使用
- 数据源：Tushare Pro（A 股）
- 目标：把真实市场历史数据压缩为“1 小时 = 1 交易日”的多人同盘回放数据

## 1. 范围与原则

- 数据使用范围：仅内部训练，不对外商业分发。
- 模式：离线导入 + 预计算压缩 + 在线只读回放。
- 回放一致性：同一赛季、同一 tick，所有玩家看到一致行情约束。
- 规则优先级：交易引擎规则（涨跌停/T+1/停牌）高于任意玩家订单。

## 2. 源接口与目标表映射

以下为推荐映射，接口名可按你实际 Tushare 账号可用接口替换：

1. 交易日历
- 源：`trade_cal`
- 目标：`trading_calendar`
- 关键字段：`exchange`, `cal_date`, `is_open`, `pretrade_date`

2. 分钟行情（1min）
- 源：分钟线接口（如 `stk_mins` / 分钟行情等）
- 目标：`raw_minute_bars`
- 关键字段：`ts_code`, `trade_time`, `open/high/low/close`, `vol`, `amount`

3. 停复牌
- 源：`suspend_d`（或等价停复牌接口）
- 目标：`trading_halts`
- 关键字段：`ts_code`, `trade_date`, `suspend_type`, `suspend_timing`

4. 复权与公司行为
- 源：`adj_factor` + 现金分红/送转相关接口（按账号权限）
- 目标：`corp_actions`
- 关键字段：`ts_code`, `ex_date`, `adjust_factor`, `cash_dividend`, `split_ratio`

5. 股票池
- 源：内部选股脚本 + 人工白名单
- 目标：`season_universe`
- 关键字段：`season_id`, `ts_code`, `role`, `event_tag`, `rank_in_theme`, `labels`

## 3. ETL 作业拆分

建议按 4 类 job 执行，状态落到 `etl_jobs`：

1. `calendar_sync`
- 拉交易日历，写入 `trading_calendar`。

2. `minute_bars_sync`
- 按股票池 + 日期窗口拉分钟线，写入 `raw_minute_bars`。
- 幂等键：`(ts_code, trade_time)`。

3. `action_sync`
- 拉复权与公司行为，写入 `corp_actions`。
- 幂等键：`(ts_code, ex_date, action_type)`。

4. `season_compress`
- 读取 raw 数据和规则，生成 `market_ticks` 与 `market_tick_quotes`。

## 4. 交易日 60 分钟结构与撮合点

单个游戏交易日固定 60 分钟：

- Minute 1-3: 开盘集合竞价（open_auction）
- Minute 4-29: 上午连续竞价（am_continuous）
- Minute 30-31: 午休（lunch_break，不可交易）
- Minute 32-57: 下午连续竞价（pm_continuous）
- Minute 58-60: 收盘集合竞价（close_auction）

匹配点（每个游戏日 12 次）：

1. 开盘集合竞价：Minute 3（open_call_auction）
2. 上午批量撮合：Minute 8/13/18/23/29（batch_match）
3. 下午批量撮合：Minute 36/41/46/51/57（batch_match）
4. 收盘集合竞价：Minute 60（close_call_auction）

备注：连续竞价区间不是逐分钟撮合，非匹配点仅受理委托/撤单（accept_only）。

## 5. 真实时间到游戏时间映射

设某真实交易日为 `D`，其分钟线区间：
- 上午：09:30-11:30
- 下午：13:00-15:00

映射建议：

1. 开盘竞价（1-3）
- 优先：若有 09:15-09:25 竞价明细则直接映射。
- 回退：若无竞价明细，用 `D` 日 `open` 与前收构造竞价锚点。

2. 上午连续（4-29, 共 26 分钟）
- 将真实上午 120 分钟切成 5 个窗口：24/24/24/24/24。
- 对应 5 个匹配点（8/13/18/23/29）。

3. 午休（30-31）
- 不可交易，价格展示可沿用最近 ref_price。

4. 下午连续（32-57, 共 26 分钟）
- 将真实下午 120 分钟切成 5 个窗口：24/24/24/24/24。
- 对应 5 个匹配点（36/41/46/51/57）。

5. 收盘竞价（58-60）
- 优先：若有收盘竞价细分数据则映射。
- 回退：以收盘窗口（14:57-15:00）构造锚点，Minute 60 执行撮合。

## 6. 压缩输出字段规范

每个 `tick + ts_code` 产出一行 `market_tick_quotes`，核心字段：

- `ref_price`: 当前 tick 的交易锚价
- `vwap_price`: 当前映射窗口的成交量加权价
- `open/high/low/close`: 映射窗口聚合值
- `volume`: 映射窗口成交量
- `volume_factor`: 成交活跃度系数（建议归一化到 [0.1, 3.0]）
- `upper_limit_price/lower_limit_price`: 涨跌停边界
- `is_halted`: 是否停牌
- `auction_imbalance_ratio`: 竞价买卖不平衡比（估算或直取）
- `auction_hint_level`: Tips 强度（0-3）

## 7. 集合竞价 Tips（严格阈值）

用户设定为“严格”，建议规则：

- 默认不展示。
- 仅用户点击 Tips 按钮时计算并返回。
- 触发条件（满足任一）：
  - `abs(auction_imbalance_ratio) >= 0.85`
  - `abs((ref_price - prev_close) / prev_close) >= 0.015`
- 显示文案只给方向性，不给确定性结论。

`auction_hint_level` 建议：
- 0: 无提示
- 1: 轻微（严格模式一般不展示）
- 2: 明显
- 3: 极端（严格模式主展示层级）

## 8. 数据质量校验（必须）

在 `season_compress` 前后执行：

1. 分钟线完整性
- 同股票同日分钟数量不低于阈值（可按停牌天例外）。
- 时间戳单调递增，无重复（依赖唯一键）。

2. 价格完整性
- O/H/L/C 全为正，且 `high >= max(open, close)`、`low <= min(open, close)`。

3. 涨跌停边界
- `upper_limit_price > lower_limit_price`。
- 回放 `ref_price` 不得越界。

4. 停牌一致性
- `is_halted=true` 的 tick 禁止撮合成交。

5. 复权一致性
- 压缩前先统一复权口径，避免赛季中出现非交易跳变。

## 9. 幂等与失败恢复

- 每个 ETL job 都在 `etl_jobs` 记录 `status/attempt/row_count/error_message`。
- 重跑策略：
  - `minute_bars_sync`: upsert 到 `raw_minute_bars`
  - `season_compress`: 先删指定 `season_id` 历史压缩数据，再全量重建
- 重试建议：最多 3 次，指数退避（30s/120s/300s）。

## 10. 运行顺序（首赛季）

1. 创建赛季记录（`seasons`）
2. 写入赛季股票池（`season_universe`）
3. 同步交易日历（`calendar_sync`）
4. 同步分钟线和公司行为（`minute_bars_sync` + `action_sync`）
5. 执行压缩（`season_compress`）
6. 运行校验并输出报告
7. 赛季开赛

## 11. 参考实现伪代码

```python
for ts_code in season_universe:
    raw = load_minute_bars(ts_code, market_dates)
    raw = apply_adjustment(raw, corp_actions)

    for game_day_no, market_date in mapping_dates:
        day_raw = raw[raw.trade_date == market_date]
        segments = build_segments(day_raw)  # open auction / am / lunch / pm / close auction

        ticks = expand_60_minutes(segments)
        for tick in ticks:
            quote = aggregate_tick_quote(tick)
            quote.upper_limit_price, quote.lower_limit_price = calc_limit(quote, prev_close)
            quote.is_halted = is_halted(ts_code, market_date)
            quote.auction_hint_level = calc_strict_hint_level(quote)
            save_quote(quote)
```

## 12. 非目标（本阶段不做）

- 实时行情联动
- 对外商用分发
- 盘中自动新闻生成
- 杠杆与衍生品
