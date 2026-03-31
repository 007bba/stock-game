"""
重新压缩数据：将每分钟tick压缩为每5分钟tick
游戏内60分钟 = 真实一天240分钟 = 4倍速

撮合点（每5分钟一次）：
- Minute 5, 10, 15（上午）
- Minute 35, 40, 45, 50, 55, 60（下午）
- Minute 15 = 开盘竞价撮合
- Minute 60 = 收盘竞价撮合
"""
import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)

# 撮合点（游戏分钟）
MATCH_MINUTES = {5, 10, 15, 35, 40, 45, 50, 55, 60}
# 开盘/收盘竞价
AUCTION_MINUTES = {15, 60}


def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    return create_engine(db_url, future=True)


def clear_old_data(engine, season_id: int):
    """删除旧的tick数据"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM market_tick_quotes WHERE season_id = :sid"), {"sid": season_id})
        conn.execute(text("DELETE FROM market_ticks WHERE season_id = :sid"), {"sid": season_id})
        LOGGER.info("Cleared old tick data for season %d", season_id)


def build_5min_ticks(conn, season_id: int, game_day_no: int, day_start_ts: pd.Timestamp) -> list[int]:
    """Create 12 ticks (5-minute intervals) for one game day."""
    tick_ids: list[int] = []

    def minute_meta(game_minute: int):
        """游戏分钟 [1,60] -> phase/mode"""
        if 1 <= game_minute <= 15:
            # 开盘集合竞价 + 早盘（真实9:30-10:30）
            if game_minute == 15:
                phase = "open_auction"
                mode = "open_call_auction"
                matching = True
            elif game_minute < 15:
                phase = "open_auction" if game_minute <= 3 else "am_continuous"
                mode = "accept_only"
                matching = False
            else:
                phase = "am_continuous"
                mode = "batch_match" if game_minute in MATCH_MINUTES else "accept_only"
                matching = game_minute in MATCH_MINUTES
            tradable = True
        elif 16 <= game_minute <= 30:
            # 上午连续竞价（真实10:30-11:30）
            phase = "am_continuous"
            mode = "batch_match" if game_minute in MATCH_MINUTES else "accept_only"
            tradable = True
            matching = game_minute in MATCH_MINUTES
        elif 31 <= game_minute <= 32:
            # 午休
            phase = "lunch_break"
            mode = "frozen"
            tradable = False
            matching = False
        elif 33 <= game_minute <= 58:
            # 下午连续竞价（真实13:00-14:30）
            phase = "pm_continuous"
            mode = "batch_match" if game_minute in MATCH_MINUTES else "accept_only"
            tradable = True
            matching = game_minute in MATCH_MINUTES
        elif 59 <= game_minute <= 60:
            # 收盘集合竞价（真实14:50-15:00）
            phase = "close_auction"
            mode = "open_call_auction" if game_minute == 60 else "accept_only"
            tradable = True
            matching = game_minute == 60
        else:
            raise ValueError(f"invalid game_minute {game_minute}")

        return phase, mode, tradable, matching

    for game_minute in range(1, 61):
        if game_minute in {31, 32}:  # 午休不创建tick
            continue

        phase, mode, tradable, matching = minute_meta(game_minute)
        scheduled_at = day_start_ts + pd.Timedelta(minutes=game_minute)

        row = conn.execute(
            text(
                """
                INSERT INTO market_ticks (
                    season_id, game_day_no, minute_of_day, phase, matching_mode,
                    is_tradable, is_matching_point, scheduled_at
                ) VALUES (
                    :season_id, :game_day_no, :minute_of_day, :phase, :mode,
                    :is_tradable, :is_matching_point, :scheduled_at
                )
                RETURNING id
                """
            ),
            {
                "season_id": season_id,
                "game_day_no": game_day_no,
                "minute_of_day": game_minute,
                "phase": phase,
                "mode": mode,
                "is_tradable": tradable,
                "is_matching_point": matching,
                "scheduled_at": scheduled_at,
            },
        ).fetchone()

        tick_ids.append(int(row[0]))

    return tick_ids


def aggregate_quotes_for_5min(raw_df: pd.DataFrame, game_minute: int, prev_close: float) -> dict:
    """
    将原始分钟数据聚合为5分钟tick
    
    游戏分钟映射：
    - Game Minute 1-15 对应真实 9:30-10:30 (60分钟，每游戏分钟=4真实分钟)
    - Game Minute 16-30 对应真实 10:30-11:30 (60分钟)
    - Game Minute 33-58 对应真实 13:00-14:30 (90分钟)
    - Game Minute 59-60 对应真实 14:50-15:00 (10分钟)
    """
    # 简化处理：每个游戏分钟对应真实4分钟
    # Game minute 1 = 真实分钟 1-4
    # Game minute 2 = 真实分钟 5-8
    start_min = (game_minute - 1) * 4 + 1
    end_min = game_minute * 4
    
    # 筛选对应的真实分钟数据
    if raw_df.empty:
        # 没有数据，返回默认值
        return {
            "ref_price": round(prev_close, 3),
            "open_price": round(prev_close, 3),
            "high_price": round(prev_close, 3),
            "low_price": round(prev_close, 3),
            "close_price": round(prev_close, 3),
            "vwap_price": round(prev_close, 3),
            "volume": 0,
            "volume_factor": 0.1,
            "upper_limit_price": round(prev_close * 1.1, 3),
            "lower_limit_price": round(prev_close * 0.9, 3),
            "is_halted": False,
            "auction_imbalance_ratio": 0.0,
            "auction_hint_level": 0,
        }
    
    # 从原始数据中提取对应的分钟
    # 假设 raw_df 有 'minute' 列（1-240）
    subset = raw_df[(raw_df['minute'] >= start_min) & (raw_df['minute'] <= end_min)]
    
    if subset.empty:
        # 没有对应数据，用最近的可用数据
        subset = raw_df
    
    # 聚合计算
    ref_price = float(subset.iloc[0]['ref_price']) if 'ref_price' in subset.columns else prev_close
    open_price = float(subset.iloc[0]['open_price'])
    close_price = float(subset.iloc[-1]['close_price'])
    high_price = float(subset['high_price'].max())
    low_price = float(subset['low_price'].min())
    volume = int(subset['vol'].sum()) if 'vol' in subset.columns else 0
    
    # VWAP
    if volume > 0:
        vwap = float((subset['close_price'] * subset['vol']).sum() / volume)
    else:
        vwap = close_price
    
    # 涨跌幅
    pct_change = ((close_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
    
    # 涨跌停判断
    upper_limit = round(prev_close * 1.1, 3)
    lower_limit = round(prev_close * 0.9, 3)
    is_limit_up = close_price >= upper_limit * 0.998
    is_limit_down = close_price <= lower_limit * 1.002
    
    # 竞价提示（简化）
    auction_hint = 0
    auction_imbalance = 0.0
    if game_minute in AUCTION_MINUTES:
        # 简化的竞价失衡计算
        auction_imbalance = (volume / (volume + 1000) - 0.5) * 2  # -1 到 1
        auction_hint = 2 if abs(auction_imbalance) > 0.3 else 1 if abs(auction_imbalance) > 0.1 else 0
    
    return {
        "ref_price": round(ref_price, 3),
        "open_price": round(open_price, 3),
        "high_price": round(high_price, 3),
        "low_price": round(low_price, 3),
        "close_price": round(close_price, 3),
        "vwap_price": round(vwap, 3),
        "volume": volume,
        "volume_factor": min(volume / 10000, 1.0),  # 归一化
        "upper_limit_price": upper_limit,
        "lower_limit_price": lower_limit,
        "is_halted": False,
        "auction_imbalance_ratio": round(auction_imbalance, 6),
        "auction_hint_level": auction_hint,
    }


def recompress_season(season_id: int):
    """重新压缩赛季数据为5分钟tick"""
    engine = get_engine()
    
    # 清除旧数据
    clear_old_data(engine, season_id)
    
    # 获取交易日列表
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT DISTINCT trade_date 
                FROM raw_minute_bars 
                WHERE season_id = :sid 
                ORDER BY trade_date
            """),
            {"sid": season_id}
        ).fetchall()
        trade_dates = [str(r[0]) for r in rows]
    
    LOGGER.info(f"Found {len(trade_dates)} trading days for season {season_id}")
    
    # 获取股票池
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT ts_code FROM season_universe WHERE season_id = :sid ORDER BY rank_in_theme"),
            {"sid": season_id}
        ).fetchall()
        universe = [str(r[0]) for r in rows]
    
    LOGGER.info(f"Found {len(universe)} stocks in universe")
    
    # 按交易日压缩
    for game_day_no, trade_date in enumerate(trade_dates, start=1):
        LOGGER.info(f"Processing day {game_day_no}/{len(trade_dates)}: {trade_date}")
        
        day_start_ts = pd.Timestamp(f"{trade_date} 20:00:00+08:00")
        
        with engine.begin() as conn:
            tick_ids = build_5min_ticks(conn, season_id, game_day_no, day_start_ts)
        
        # 为每只股票生成quotes
        for ts_code in universe:
            with engine.connect() as conn:
                # 加载原始分钟数据
                rows = conn.execute(
                    text("""
                        SELECT minute, open_price, high_price, low_price, close_price, vol, ref_price
                        FROM raw_minute_bars
                        WHERE season_id = :sid AND ts_code = :code AND trade_date = :date
                        ORDER BY minute
                    """),
                    {"sid": season_id, "code": ts_code, "date": trade_date}
                ).fetchall()
                
                if not rows:
                    # 没有数据，跳过
                    continue
                
                raw_df = pd.DataFrame(rows, columns=['minute', 'open_price', 'high_price', 'low_price', 'close_price', 'vol', 'ref_price'])
                
                # 获取前收盘价
                prev_close = float(rows[0][6]) if rows else 10.0  # ref_price
            
            # 为每个tick生成quote
            with engine.begin() as conn:
                for game_minute, tick_id in enumerate(tick_ids, start=1):
                    if game_minute in {31, 32}:  # 午休
                        continue
                    
                    quote = aggregate_quotes_for_5min(raw_df, game_minute, prev_close)
                    
                    conn.execute(
                        text("""
                            INSERT INTO market_tick_quotes (
                                tick_id, season_id, ts_code, ref_price,
                                open_price, high_price, low_price, close_price, vwap_price,
                                upper_limit_price, lower_limit_price, is_halted,
                                volume, volume_factor, auction_imbalance_ratio, auction_hint_level
                            ) VALUES (
                                :tick_id, :season_id, :ts_code, :ref_price,
                                :open_price, :high_price, :low_price, :close_price, :vwap_price,
                                :upper_limit_price, :lower_limit_price, :is_halted,
                                :volume, :volume_factor, :auction_imbalance_ratio, :auction_hint_level
                            )
                        """),
                        {
                            "tick_id": tick_id,
                            "season_id": season_id,
                            "ts_code": ts_code,
                            **quote
                        }
                    )
    
    LOGGER.info(f"Recompression completed for season {season_id}")


def main():
    parser = argparse.ArgumentParser(description="Recompress season data to 5-minute ticks")
    parser.add_argument("--season-id", type=int, required=True, help="Season ID")
    args = parser.parse_args()
    
    recompress_season(args.season_id)


if __name__ == "__main__":
    main()
